"""Learning artifacts from explicitly labelled native-video observations, never fake speech."""

import re
from dataclasses import dataclass

from youtube_backend.schemas import (
    AnswerResult,
    ArtifactResult,
    Citation,
    Coverage,
    ProviderMetadata,
)
from youtube_backend.video_evidence import VideoEvidenceStore

from .gemini import byte_size
from .models import error


@dataclass
class VideoLearningEvidence:
    observation: dict

    def model_dump(self):
        return dict(
            evidence_id=self.observation["evidence_id"],
            kind="video_observation",
            observation_kind=self.observation["kind"],
            text=self.observation["text"],
            video_id=self.observation["video_id"],
            start_seconds=self.observation["start_seconds"],
            end_seconds=self.observation["end_seconds"],
        )


async def video_artifact(service, request, run, schema):
    plan = learning_plan(run.sources[0], request["topic"])
    native = await stored_video(service, request, run, plan=plan)
    if native is None:
        native = await service._bounded(
            run,
            lambda _: service.media_answerer(request["topic"], run.sources, run.context),
            model=True,
        )
    if native is None:
        return None
    if native.status != "answered" or not native.citations:
        raise error(
            "insufficient_evidence",
            "Video evidence is insufficient for this learning topic",
            status=409,
        )
    if any(not within_plan(c, plan) for c in native.citations):
        raise error("invalid_citation", "Video learning evidence exceeds the requested time window")
    records = VideoEvidenceStore(run.context).resolve(native.citations)
    evidence = []
    for record in records:
        candidate = [*evidence, VideoLearningEvidence(record)]
        if (
            byte_size({"request": request, "evidence": [e.model_dump() for e in candidate]})
            <= service.settings.max_context_tokens // 2
        ):
            evidence = candidate
    if not evidence:
        raise error(
            "context_budget_exceeded", "Full video observations exceed learning input budget"
        )
    supplied = {e.observation["evidence_id"] for e in evidence}
    generated = await service._bounded(
        run,
        lambda timeout: service.model.generate(
            request, evidence, schema, timeout, context=run.context, citation_key="evidence_id"
        ),
        model=True,
    )
    content = schema.model_validate(generated.content)
    items = getattr(
        content, {"quiz": "questions", "flashcards": "cards", "study_plan": "days"}[request["type"]]
    )
    from .quality import validate_learning_items

    validate_learning_items(request["type"], items)
    ids = {cid for item in items for cid in item.citations}
    allowed = {c.chunk_id: c for c in native.citations if c.chunk_id in supplied}
    if not ids.issubset(allowed) or not ids:
        raise error("invalid_citation", "Video artifact cites unknown observations")
    if request["type"] == "study_plan" and len(items) != request["days"]:
        raise error("invalid_artifact", "Study plan day count does not match request")
    metadata = generated.metadata.model_copy(deep=True)
    for key, count in native.provider_metadata.usage.items():
        metadata.usage[key] = metadata.usage.get(key, 0) + count
    metadata.latency_ms += native.provider_metadata.latency_ms
    coverage = native.coverage.model_copy(deep=True)
    coverage.processed_videos = len({e.observation["video_id"] for e in evidence})
    if len(evidence) < len(records):
        coverage.notes.append("ใช้หลักฐานฉบับเต็มบางรายการเพื่อให้อยู่ในขีดจำกัดข้อมูล")
    return ArtifactResult(
        type=request["type"],
        content=content,
        citations=[allowed[cid].model_copy(update={"citation_id": cid}) for cid in sorted(ids)],
        coverage=coverage,
        provider_metadata=metadata,
    )


def learning_plan(source, topic):
    try:
        from youtube_ingestion.video_plan import VideoPlan
    except ImportError:
        raise error(
            "integration_not_installed",
            "Native learning requires the shared video planner",
            status=503,
        ) from None
    return VideoPlan.from_question(source, topic)


def within_plan(citation, plan):
    return citation.start_seconds >= plan.start_seconds and citation.end_seconds <= (
        plan.end_seconds if plan.end_seconds is not None else 7200
    )


async def stored_video(service, request, run, *, plan=None):
    """Use 04's private observation catalogue before spending a vision call.

    Older 04 installations keep the native path. Relevance is a candidate filter,
    not semantic proof; generation receives the complete observations and caveats.
    """
    if len(run.sources) != 1:
        return None  # Preserve the existing single-video native contract until P3.
    plan = plan or learning_plan(run.sources[0], request["topic"])
    rag = getattr(service.knowledge, "rag", None)
    factory = getattr(rag, "evidence_library", None)
    if not callable(factory):
        return None
    # Clock tokens constrain the lookup window; they are not lexical topic terms.
    lookup_topic = re.sub(r"(?<![\d:])[\d:]*\d:[\d:]+(?![\d:])", " ", request["topic"]).strip()
    if not any(char.isalnum() for char in lookup_topic):
        return None
    result = await service._bounded(
        run,
        lambda _: factory().search(
            lookup_topic,
            run.sources,
            run.context,
            kinds=["video"],
            limit=16,
            start_seconds=plan.start_seconds,
            end_seconds=plan.end_seconds,
        ),
    )
    candidates = [
        r
        for r in result.items
        if r.ranking_score >= 0.5 and within_plan(Citation.model_validate(r.citation), plan)
    ]
    if not candidates:
        return None
    return AnswerResult(
        status="answered",
        answer="Stored video observations selected for learning generation.",
        citations=[Citation.model_validate(r.citation) for r in candidates],
        coverage=Coverage(
            expected_videos=len(run.sources),
            processed_videos=len({r.source.video_id for r in candidates}),
            complete=False,
            notes=[
                "Reused stored sampled observations; whole-video coverage is not established.",
                *result.notes,
            ],
        ),
        provider_metadata=ProviderMetadata(
            provider="evidence-library",
            requested_model=service.settings.llm_model,
            returned_model=None,
            usage={},
            latency_ms=0,
        ),
    )
