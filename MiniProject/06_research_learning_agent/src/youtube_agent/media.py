"""Opt-in media controller: backend v2 citations, no synthetic transcript or public route.

The native 02/04 media path currently admits enrichment leases only. Planning and
vision require a server-provided 05 bridge and a job allowed by 02's broker policy.
"""

import asyncio
import hashlib
import time
from typing import Literal

from pydantic import Field
from youtube_backend.evidence_v2 import SourceSnapshotV2, VisualCitationV2
from youtube_backend.schemas import ProgressEvent, Schema

from .gemini import byte_size, json_text
from .models import FinishArgs, SearchArgs, error
from .service import CONTENTS


class InspectFrame(Schema):
    frame_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class MediaRequest(Schema):
    goal: str = Field(min_length=1, max_length=12000)
    artifact_type: Literal["quiz", "flashcards", "study_plan"] | None = None
    days: int = Field(default=7, ge=1, le=30)


class MediaRecord(Schema):
    evidence_id: str = Field(min_length=1, max_length=300)
    citation: VisualCitationV2


MEDIA_TOOLS = {
    "search_prepared_media": SearchArgs,
    "inspect_frame": InspectFrame,
    "finish_research": FinishArgs,
}
WAIT_CODES = {
    "free_tier_unverified",
    "free_model_unverified",
    "quota_wait",
    "quota_pending",
    "quota_policy_mismatch",
    "provider_rate_limited",
    "provider_unavailable",
}


class MediaAgentService:
    """Tools authorize/inventory/search/evidence/frames; optional vision.observe is 05-owned.

    authorize returns an opaque durable owner/job/grant/snapshot fingerprint. frames
    returns authorized prepared frame IDs, not paths or arbitrary URLs. observe must
    use 05's cache and the supplied context's shared 02 broker. Every cache hit is
    revalidated. Output is an internal v2 handoff, not a v1 ResearchResult for 02.finish.
    """

    def __init__(self, settings, tools, *, planner=None, vision=None):
        self.settings, self.tools, self.planner, self.vision = settings, tools, planner, vision

    async def research(self, request, snapshots, context):
        request = MediaRequest.model_validate(request)
        sources = tuple(SourceSnapshotV2.model_validate(s).model_copy(deep=True) for s in snapshots)
        if (
            not sources
            or any(s.kind == "transcript" for s in sources)
            or len(set((s.video_id, s.kind) for s in sources)) != len(sources)
        ):
            raise error(
                "invalid_scope", "Provide distinct prepared OCR/visual snapshots", status=403
            )
        context.check()
        token = self.tools.authorize(sources, context)
        if not isinstance(token, str) or not token:
            raise error("member_access_denied", "Trusted media authority required", status=403)
        deadline = time.monotonic() + min(
            context.remaining_seconds, self.settings.agent_timeout_seconds
        )
        records, inspected, actions = {}, set(), set()
        tool_calls = model_calls = 0

        def check():
            context.check()
            if self.tools.authorize(sources, context) != token:
                raise error("member_access_denied", "Media permission changed", status=403)

        async def call(function, *, final=False, model=False, both=False):
            nonlocal tool_calls, model_calls
            check()
            if model:
                if model_calls >= self.settings.agent_max_model_calls:
                    raise error("agent_budget_exhausted", "Media model budget exhausted")
                model_calls += 1
            if not model or both:
                limit = self.settings.agent_max_tool_calls - (1 if not final else 0)
                if tool_calls >= limit:
                    raise error("agent_budget_exhausted", "Media tool budget exhausted")
                tool_calls += 1
            left = min(deadline - time.monotonic(), context.remaining_seconds)
            left -= 0 if final else self.settings.agent_finalize_reserve_seconds
            if left <= 0:
                raise error("agent_budget_exhausted", "Media final validation time reserve reached")
            async with asyncio.timeout(left):
                result = await function()
            check()
            return result

        def remember(values):
            for value in values:
                record = MediaRecord.model_validate(value)
                if record.citation.source not in sources:
                    raise error("invalid_scope", "Media evidence exceeds frozen scope", status=403)
                old = records.get(record.evidence_id)
                if old is not None and old != record:
                    raise error("source_changed", "Media evidence changed within this run")
                records[record.evidence_id] = record
            if (
                len(records) > 100
                or byte_size([r.model_dump() for r in records.values()])
                > self.settings.max_context_tokens // 2
            ):
                raise error("context_budget_exceeded", "Prepared media exceeds bounded context")

        def event(name, summary):
            check()
            context.event(
                ProgressEvent(step=tool_calls, tool_name=name, state="running", summary=summary)
            )

        async def deliver(content, ids, *, state="partial", reason=None, artifact=None):
            if any(cid not in records for cid in ids):
                raise error("invalid_citation", "Media output cites an uninspected evidence ID")
            exported = [records[cid] for cid in dict.fromkeys(ids)]
            current = await call(
                lambda: self.tools.evidence(sources, list(dict.fromkeys(ids)), context), final=True
            )
            fresh = {r.evidence_id: r for r in map(MediaRecord.model_validate, current)}
            if fresh != {r.evidence_id: r for r in exported}:
                raise error("source_changed", "Media changed before delivery")
            check()
            context.event(
                ProgressEvent(
                    step=tool_calls,
                    tool_name="run_controller",
                    state=state,
                    summary=f"Validated sampled media; model_calls={model_calls}; "
                    f"additional_frames={len(inspected)}; whole_video_reviewed=False",
                )
            )
            return {
                "schema_version": "06-media-v1",
                "state": state,
                "content": content,
                "citations": [r.model_dump(mode="json") for r in exported],
                "artifact": artifact,
                "reason": reason,
                "model_calls": model_calls,
                "tool_calls": tool_calls,
                "visual_coverage": {
                    "whole_video_reviewed": False,
                    "inspected_frame_ids": sorted({r.citation.frame_id for r in records.values()}),
                    "additional_frame_count": len(inspected),
                },
            }

        try:
            readiness = await call(lambda: self.tools.inventory(sources, context))
            event("search_prepared_media", "Search stored OCR and visual descriptions first")
            remember(await call(lambda: self.tools.search(request.goal, sources, context)))
            history = [
                {
                    "role": "user",
                    "data": {
                        "request": request.model_dump(),
                        "readiness": readiness,
                        "evidence": [r.model_dump() for r in records.values()],
                        "limitations": "Samples only; OCR is not speech; no identity inference.",
                    },
                }
            ]
            if self.planner is None:
                raise error("quota_pending", "Media planning bridge is not enabled", status=503)
            for _ in range(self.settings.agent_max_steps):
                final_only = model_calls >= self.settings.agent_max_model_calls - (
                    2 if request.artifact_type else 1
                )
                history.append({"role": "user", "data": {"final_only": final_only}})
                if (
                    byte_size([{k: v for k, v in h.items() if k != "native"} for h in history])
                    > self.settings.max_context_tokens // 2
                ):
                    raise error("context_budget_exceeded", "Media history exceeds context budget")
                reply = await call(
                    lambda: self.planner.decide(
                        history, context.remaining_seconds, context=context, tools=MEDIA_TOOLS
                    ),
                    model=True,
                )
                if reply.name not in MEDIA_TOOLS:
                    raise error("invalid_tool_call", "Unsupported media action")
                args = MEDIA_TOOLS[reply.name].model_validate(reply.arguments)
                if final_only and reply.name != "finish_research":
                    raise error("agent_budget_exhausted", "Final answer allowance preserved")
                if reply.name == "finish_research":
                    artifact = None
                    if request.artifact_type:
                        if not records:
                            raise error(
                                "insufficient_evidence", "Learning output needs media evidence"
                            )
                        schema = CONTENTS[request.artifact_type]
                        generated = await call(
                            lambda output_schema=schema: self.planner.generate(
                                {
                                    "type": request.artifact_type,
                                    "topic": request.goal,
                                    "days": request.days,
                                },
                                list(records.values()),
                                output_schema,
                                context.remaining_seconds,
                                context=context,
                                citation_key="evidence_id",
                            ),
                            model=True,
                        )
                        artifact = schema.model_validate(generated.content).model_dump(mode="json")
                        items = next(iter(artifact.values()))
                        ids = sorted({cid for item in items for cid in item["citations"]})
                        if request.artifact_type == "study_plan" and len(items) != request.days:
                            raise error("invalid_artifact", "Media study plan day count mismatch")
                    else:
                        ids = args.citation_ids
                    if not ids:
                        raise error("insufficient_evidence", "Final media output needs citations")
                    return await deliver(args.content, ids, state="completed", artifact=artifact)
                fingerprint = hashlib.sha256(
                    json_text([reply.name, args.model_dump()]).encode()
                ).hexdigest()
                if fingerprint in actions:
                    raise error("agent_budget_exhausted", "Repeated media action stopped")
                actions.add(fingerprint)
                history.append(
                    {
                        "role": "model",
                        "native": reply.native,
                        "name": reply.name,
                        "arguments": reply.arguments,
                    }
                )
                if reply.name == "search_prepared_media":
                    remember(
                        await call(
                            lambda query=args.query: self.tools.search(query, sources, context)
                        )
                    )
                else:
                    known = {
                        r.citation.frame_id
                        for r in records.values()
                        if r.citation.source.kind == "visual"
                    }
                    if args.frame_id not in known and args.frame_id not in inspected:
                        allowed = await call(lambda: self.tools.frames(sources, context))
                        if args.frame_id not in allowed:
                            raise error("invalid_scope", "Frame is not authorized", status=403)
                    if args.frame_id in known or args.frame_id in inspected:
                        observation = {"cached": True}
                    else:
                        if self.vision is None:
                            raise error(
                                "quota_pending",
                                "Module 05 vision bridge is not enabled",
                                status=503,
                            )
                        if (
                            len(inspected) >= self.settings.agent_max_extra_frames
                            or model_calls >= self.settings.agent_max_model_calls - 1
                        ):
                            raise error("agent_budget_exhausted", "No extra image allowance")
                        event(
                            "inspect_frame",
                            "Ask module 05 to inspect one authorized prepared frame",
                        )
                        observed = await call(
                            lambda frame_id=args.frame_id: self.vision.observe(
                                frame_id, sources, context
                            ),
                            model=True,
                            both=True,
                        )
                        checked = [MediaRecord.model_validate(r) for r in observed]
                        if any(
                            r.citation.frame_id != args.frame_id
                            or r.citation.source.kind != "visual"
                            for r in checked
                        ):
                            raise error(
                                "invalid_scope", "05 returned an unrequested frame", status=403
                            )
                        remember([r.model_dump() for r in checked])
                        inspected.add(args.frame_id)
                        observation = {"cached": False}
                if reply.name == "search_prepared_media":
                    observation = {}
                observation["evidence"] = [r.model_dump() for r in records.values()]
                native_calls = (
                    [p.function_call for p in reply.native.parts or [] if p.function_call]
                    if reply.native
                    else []
                )
                history.append(
                    {
                        "role": "tool",
                        "name": reply.name,
                        "result": observation,
                        "call_id": native_calls[0].id if native_calls else None,
                    }
                )
            raise error("agent_budget_exhausted", "Media step budget exhausted")
        except Exception as exc:
            # Never turn ownership, malformed citations or source changes into partial exports.
            from youtube_backend.errors import AppError

            if not isinstance(exc, TimeoutError) and not (
                isinstance(exc, AppError)
                and (
                    exc.code
                    in WAIT_CODES
                    | {"agent_budget_exhausted", "context_budget_exceeded", "insufficient_evidence"}
                )
            ):
                raise
            reason = getattr(exc, "code", "agent_budget_exhausted")
            excerpts = "\n".join(
                f"[{r.evidence_id}] {r.citation.text[:500]}" for r in records.values()
            )
            return await deliver(
                "Partial sampled evidence; not all video frames reviewed.\n" + excerpts,
                list(records),
                reason=reason,
            )
