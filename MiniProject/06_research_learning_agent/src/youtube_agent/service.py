"""Observation-driven orchestration. Persistence and execution ownership stay in 02."""

import asyncio
import time
from dataclasses import dataclass, field

from pydantic import ValidationError
from youtube_backend.errors import AppError
from youtube_backend.schemas import (
    AnswerResult,
    ArtifactRequest,
    ArtifactResult,
    Citation,
    Coverage,
    Evidence,
    FlashcardsContent,
    ProgressEvent,
    QuizContent,
    ResearchRequest,
    ResearchResult,
    Source,
    StudyPlanContent,
)
from youtube_backend.urls import canonical_url

from .authorization import member_service
from .gemini import byte_size, json_text
from .models import TOOL_MODELS, Usage, error

CONTENTS = {"study_plan": StudyPlanContent, "quiz": QuizContent, "flashcards": FlashcardsContent}
SOURCE_ERRORS = {
    "source_changed",
    "invalid_evidence",
    "index_configuration_mismatch",
    "index_incomplete",
    "incomplete_index",
    "invalid_coverage",
}


@dataclass
class Run:
    sources: list
    context: object
    end: float
    usage: Usage
    total: int | None = None
    evidence: dict = field(default_factory=dict)
    processed: set = field(default_factory=set)
    pending: set = field(default_factory=set)
    artifacts: list = field(default_factory=list)
    step: int = 0

    def remaining(self):
        self.context.check()
        return min(self.end - time.monotonic(), self.context.remaining_seconds)


class AgentService:
    def __init__(self, settings, model, knowledge, *, analyzer=None):
        self.settings = settings
        self.model = model
        self.knowledge = knowledge
        self.analyzer = analyzer

    def _run(self, sources, context):
        context.check()
        sources = [Source.model_validate(s) for s in sources]
        if not sources or len({s.video_id for s in sources}) != len(sources):
            raise error("invalid_scope", "Provide distinct authorized sources", status=422)
        # 04's BackendExecution authorizes generations/versions against the durable job.
        return Run(
            sources,
            context,
            time.monotonic() + min(self.settings.agent_timeout_seconds, context.remaining_seconds),
            Usage(self.settings.llm_model, provider="none"),
        )

    async def _bounded(self, run, function, *, reserve=True):
        remaining = run.remaining() - (
            self.settings.agent_finalize_reserve_seconds if reserve else 0
        )
        if remaining <= 0:
            raise error("agent_budget_exhausted", "Research finalization reserve reached")
        before_call = getattr(run.context, "before_agent_call", None)
        if before_call is not None:
            before_call()
        async with asyncio.timeout(min(remaining, self.settings.llm_timeout_seconds)):
            value = await function(min(remaining, self.settings.llm_timeout_seconds))
        run.context.check()
        return value

    def _event(self, run, step, name, state, summary):
        run.context.event(ProgressEvent(step=step, tool_name=name, state=state, summary=summary))

    def _records(self, run, values, *, sources=None):
        allowed = {s.video_id: s for s in (sources if sources is not None else run.sources)}
        records = [Evidence.model_validate(v) for v in values]
        unique = {}
        for item in records:
            source = allowed.get(item.video_id)
            if not source or source.transcript_version != item.transcript_version:
                raise error("invalid_evidence", "Tool evidence exceeds authorized sources")
            old = unique.get(item.chunk_id, run.evidence.get(item.chunk_id))
            if old is not None and old != item:
                raise error("invalid_evidence", "Evidence ID changed within the run")
            unique[item.chunk_id] = item
        if run.total is not None and len(set(run.evidence) | set(unique)) > run.total:
            raise error("invalid_coverage", "Evidence exceeds the indexed chunk inventory")
        return list(unique.values())

    def _request(self, schema, request, run):
        request = schema.model_validate(request).model_dump(mode="json")
        # Channel/date filters may legitimately narrow the original explicit video set in 02.
        if not {s.video_id for s in run.sources}.issubset(request["scope"]["video_ids"]):
            raise error(
                "invalid_scope", "Authorized sources exceed the requested videos", status=422
            )
        return request

    async def _deliver(self, run, result):
        """Recheck exported evidence before using the finalization reserve to publish."""
        citations = list(result.citations)
        for artifact in getattr(result, "artifacts", []):
            citations.extend(artifact.citations)
        ids = sorted({c.chunk_id for c in citations})
        for offset in range(0, len(ids), 1000):
            batch = ids[offset : offset + 1000]
            current = await self._bounded(
                run,
                lambda _, chunk_ids=batch: self.knowledge.evidence(
                    run.sources, chunk_ids, run.context
                ),
                reserve=False,
            )
            records = self._records(run, current)
            if {e.chunk_id for e in records} != set(batch):
                raise error("source_changed", "Cited evidence is no longer available")
            if any(e != run.evidence[e.chunk_id] for e in records):
                raise error("source_changed", "Cited evidence changed before finalization")
        if run.total is not None:
            count = await self._bounded(
                run, lambda _: self.knowledge.inventory(run.sources, run.context), reserve=False
            )
            if type(count) is not int or count != run.total:
                raise error("source_changed", "Index inventory changed before finalization")
        run.context.check()
        state = getattr(result, "state", "completed")
        self._event(
            run,
            run.step,
            "run_controller",
            state,
            f"Validated output; processed_chunks={result.coverage.processed_chunks}; "
            f"complete={result.coverage.complete}",
        )
        return result

    def _remember(self, run, records):
        run.evidence.update({e.chunk_id: e for e in records})

    def _citations(self, run, ids):
        ids = list(dict.fromkeys(ids))
        if any(i not in run.evidence for i in ids):
            raise error("invalid_citation", "Unknown evidence citation ID")
        result = []
        for cid in ids:
            record = run.evidence[cid]
            result.append(
                Citation(
                    citation_id=cid,
                    chunk_id=record.chunk_id,
                    video_id=record.video_id,
                    title=record.title,
                    start_seconds=record.start_seconds,
                    end_seconds=record.end_seconds,
                    url=f"{canonical_url(record.video_id)}&t={int(record.start_seconds)}s",
                )
            )
        return result

    def _coverage(self, run, note=None):
        videos = {run.evidence[c].video_id for c in run.processed}
        complete = (
            run.total is not None
            and run.total > 0
            and len(run.processed) == run.total
            and len(videos) == len(run.sources)
        )
        notes = (
            []
            if complete
            else [
                "Only evidence actually supplied to successful model calls "
                "is counted; unprocessed sources may remain."
            ]
        )
        if note:
            notes.append(note)
        return Coverage(
            expected_videos=len(run.sources),
            processed_videos=len(videos),
            expected_chunks=run.total,
            processed_chunks=len(run.processed) if run.total is not None else None,
            complete=complete,
            notes=notes,
        )

    def _subset(self, run, ids):
        if not ids:
            return run.sources
        allowed = {s.video_id: s for s in run.sources}
        if len(set(ids)) != len(ids) or any(i not in allowed for i in ids):
            raise error(
                "invalid_scope", "Tool selected unauthorized or duplicate videos", status=422
            )
        return [allowed[i] for i in ids]

    def _input_fits(self, payload):
        # Reserve half for instructions, native model signatures, tools and output schemas.
        # Live preflight counts native contents and reserves configuration byte overhead.
        if byte_size(payload) > self.settings.max_context_tokens // 2:
            raise error("context_budget_exceeded", "Evidence/history exceeds local byte guard")

    async def _inventory(self, run):
        count = await self._bounded(
            run, lambda _: self.knowledge.inventory(run.sources, run.context)
        )
        if type(count) is not int or count < 0:
            raise error("invalid_coverage", "Knowledge inventory is invalid")
        run.total = count

    async def _artifact(self, request, run):
        # Full enumeration is bounded; a context overflow is explicit, never silently truncated.
        records, cursor, cursors = {}, None, set()
        while True:
            page = await self._bounded(
                run,
                lambda _, page_cursor=cursor: self.knowledge.read(
                    run.sources,
                    run.context,
                    limit=self.settings.agent_read_page_size,
                    cursor=page_cursor,
                ),
            )
            batch = self._records(
                run, [e.evidence() if hasattr(e, "evidence") else e for e in page.items]
            )
            records.update({e.chunk_id: e for e in batch})
            self._input_fits(
                {"request": request, "evidence": [e.model_dump() for e in records.values()]}
            )
            self._remember(run, batch)
            cursor = page.next_cursor
            if cursor is None:
                break
            if cursor in cursors or not batch:
                raise error("invalid_cursor", "Knowledge pagination made no progress")
            cursors.add(cursor)
        if not records:
            raise error(
                "insufficient_evidence", "No transcript evidence for learning output", status=409
            )
        schema = CONTENTS[request["type"]]
        generated = await self._bounded(
            run,
            lambda timeout: self.model.generate(request, list(records.values()), schema, timeout),
        )
        run.usage.add(generated.metadata)
        try:
            content = schema.model_validate(generated.content)
            items = getattr(
                content,
                {"study_plan": "days", "quiz": "questions", "flashcards": "cards"}[request["type"]],
            )
            ids = {cid for item in items for cid in item.citations}
            if not ids.issubset(records):
                raise error(
                    "invalid_citation", "Artifact cites evidence not supplied to generation"
                )
            if request["type"] == "study_plan" and len(items) != request["days"]:
                raise error("invalid_artifact", "Study plan day count does not match request")
            citations = self._citations(run, sorted(ids))
            # Validate before crediting processed evidence or exposing an artifact.
            artifact = ArtifactResult(
                type=request["type"],
                content=content,
                citations=citations,
                coverage=self._coverage(run),
                provider_metadata=generated.metadata,
            )
        except ValidationError:
            raise error(
                "invalid_artifact", "Generated artifact does not match its schema"
            ) from None
        run.processed.update(records)
        artifact.coverage = self._coverage(run)
        return artifact

    async def artifact(self, request, sources, context):
        member = member_service(self, context)
        if member is not None:
            return await member.artifact(request, sources, context)
        run = self._run(sources, context)
        request = self._request(ArtifactRequest, request, run)
        try:
            self._event(run, 0, "create_learning_artifact", "running", "Collecting scoped evidence")
            await self._inventory(run)
            result = await self._artifact(request, run)
            return await self._deliver(run, result)
        except TimeoutError:
            raise error(
                "agent_budget_exhausted", "Artifact exceeded its time budget", status=504
            ) from None

    async def _tool(self, name, args, request, run):
        if name == "search_evidence":
            hits = await self._bounded(
                run,
                lambda _: self.knowledge.search(
                    args.query, run.sources, run.context, top_k=args.top_k
                ),
            )
            records = self._records(run, [h.chunk.evidence() for h in hits])
            observation = {"evidence": [e.model_dump() for e in records]}
        elif name == "read_video_chunks":
            sources = self._subset(run, args.video_ids)
            page = await self._bounded(
                run,
                lambda _: self.knowledge.read(
                    sources, run.context, limit=args.limit, cursor=args.cursor
                ),
            )
            records = self._records(run, [e.evidence() for e in page.items], sources=sources)
            observation = {
                "evidence": [e.model_dump() for e in records],
                "next_cursor": page.next_cursor,
                "total": page.total,
            }
        elif name == "compare_videos":
            sources = self._subset(run, args.video_ids)
            if self.analyzer is None:
                raise error(
                    "analysis_unavailable", "Module 05 comparison is not connected", status=503
                )
            answer = AnswerResult.model_validate(
                await self._bounded(
                    run,
                    lambda _: self.analyzer(
                        {
                            "type": "compare",
                            "instruction": args.instruction,
                            "scope": {"video_ids": args.video_ids},
                        },
                        sources,
                        run.context,
                    ),
                )
            )
            ids = [c.chunk_id for c in answer.citations]
            records = self._records(
                run,
                await self._bounded(
                    run, lambda _: self.knowledge.evidence(sources, ids, run.context)
                ),
                sources=sources,
            )
            if len({c.citation_id for c in answer.citations}) != len(answer.citations):
                raise error("invalid_citation", "Comparison citation IDs are not unique")
            by_id = {e.chunk_id: e for e in records}
            for citation in answer.citations:
                evidence = by_id.get(citation.chunk_id)
                if not evidence or (
                    citation.video_id,
                    citation.start_seconds,
                    citation.end_seconds,
                ) != (evidence.video_id, evidence.start_seconds, evidence.end_seconds):
                    raise error("invalid_citation", "Comparison citation does not match evidence")
            if answer.status == "answered" and not records:
                raise error("invalid_citation", "Comparison answer needs evidence")
            run.usage.add(answer.provider_metadata)
            observation = {
                "answer": answer.answer,
                "status": answer.status,
                "citations": [c.model_dump() for c in answer.citations],
                "coverage": answer.coverage.model_dump(),
                "evidence": [e.model_dump() for e in records],
            }
        else:
            artifact_request = ArtifactRequest(
                type=args.type,
                topic=args.topic or request["goal"],
                level=request["level"],
                days=request["days"],
                scope=request["scope"],
            ).model_dump(mode="json")
            artifact = await self._artifact(artifact_request, run)
            run.artifacts.append(artifact)
            return {
                "artifact_type": artifact.type,
                "created": True,
                "citation_ids": [c.citation_id for c in artifact.citations],
            }
        self._input_fits(observation)
        self._remember(run, records)
        run.pending.update(e.chunk_id for e in records)
        return observation

    def _partial(self, run, reason):
        ids = sorted(run.processed or set(run.evidence))[:8]
        # No new model claims: preserve source excerpts with an explicit analysis limitation.
        content = "Research stopped with partial findings. " + reason
        if ids:
            content += "\nRetrieved source excerpts (may be incompletely analyzed):\n" + "\n".join(
                f"[{cid}] {run.evidence[cid].text[:500]}" for cid in ids
            )
        else:
            content += " No supporting evidence was obtained."
        return ResearchResult(
            state="partial",
            content=content,
            artifacts=run.artifacts,
            citations=self._citations(run, ids),
            coverage=self._coverage(run, reason),
            provider_metadata=run.usage.result(),
        )

    async def research(self, request, sources, context):
        member = member_service(self, context)
        if member is not None:
            return await member.research(request, sources, context)
        run = self._run(sources, context)
        request = self._request(ResearchRequest, request, run)
        history = [
            {
                "role": "user",
                "data": {
                    "request": request,
                    "authorized_sources": [s.model_dump() for s in run.sources],
                },
            }
        ]
        seen = set()
        try:
            await self._inventory(run)
            for step in range(1, self.settings.agent_max_steps + 1):
                run.step = step
                self._input_fits(
                    [{k: v for k, v in entry.items() if k != "native"} for entry in history]
                )
                history.append(
                    {
                        "role": "user",
                        "data": {
                            "remaining_steps": self.settings.agent_max_steps - step + 1,
                            "remaining_seconds": max(0, run.remaining()),
                            "coverage": self._coverage(run).model_dump(),
                        },
                    }
                )
                reply = await self._bounded(
                    run, lambda timeout: self.model.decide(history, timeout)
                )
                run.usage.add(reply.metadata)
                # Only credit observations after the subsequent decision successfully returned.
                run.processed.update(run.pending)
                run.pending.clear()
                history.append(
                    {
                        "role": "model",
                        "native": reply.native,
                        "name": reply.name,
                        "arguments": reply.arguments,
                    }
                )
                if reply.name not in TOOL_MODELS:
                    raise error("invalid_tool_call", "Agent requested an unsupported tool")
                try:
                    args = TOOL_MODELS[reply.name].model_validate(reply.arguments)
                except ValidationError:
                    self._event(run, step, reply.name, "rejected", "Invalid tool arguments")
                    observation = {"error": "invalid_tool_arguments"}
                else:
                    fingerprint = (reply.name, json_text(args.model_dump()))
                    if fingerprint in seen:
                        return await self._deliver(
                            run, self._partial(run, "Repeated action without a new observation.")
                        )
                    seen.add(fingerprint)
                    self._event(
                        run, step, reply.name, "running", "Executing validated scoped action"
                    )
                    if reply.name == "finish_research":
                        if not args.citation_ids:
                            return await self._deliver(
                                run, self._partial(run, "No cited final answer was supplied.")
                            )
                        citations = self._citations(run, args.citation_ids)
                        coverage = self._coverage(run)
                        result = ResearchResult(
                            state="completed" if coverage.complete else "partial",
                            content=args.content,
                            citations=citations,
                            artifacts=run.artifacts,
                            coverage=coverage,
                            provider_metadata=run.usage.result(),
                        )
                        self._event(run, step, reply.name, "validating", "Rechecking final sources")
                        return await self._deliver(run, result)
                    try:
                        observation = await self._tool(reply.name, args, request, run)
                    except AppError as exc:
                        if exc.code not in {"invalid_scope", "analysis_unavailable"}:
                            raise
                        observation = {"error": exc.code}
                    self._event(
                        run,
                        step,
                        reply.name,
                        "rejected" if "error" in observation else "completed",
                        "Scoped observation recorded",
                    )
                call_id = None
                if reply.native is not None:
                    calls = [p.function_call for p in reply.native.parts or [] if p.function_call]
                    call_id = calls[0].id if calls else None
                history.append(
                    {"role": "tool", "name": reply.name, "call_id": call_id, "result": observation}
                )
            return await self._deliver(
                run, self._partial(run, "Agent decision step limit reached.")
            )
        except TimeoutError:
            context.check()
            return await self._deliver(
                run, self._partial(run, "Agent operation exceeded its remaining time budget.")
            )
        except AppError as exc:
            context.check()
            if exc.code in SOURCE_ERRORS:
                raise
            if exc.code in {"agent_budget_exhausted", "context_budget_exceeded"} or run.evidence:
                return await self._deliver(run, self._partial(run, f"Stopped: {exc.code}."))
            raise
