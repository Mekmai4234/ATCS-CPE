"""Learning artifacts from explicitly labelled native-video observations, never fake speech."""

from dataclasses import dataclass

from youtube_backend.schemas import ArtifactResult
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
    if len(evidence) < len(records):
        coverage.notes.append("ใช้หลักฐานฉบับเต็มบางรายการเพื่อให้อยู่ในขีดจำกัดข้อมูล")
    return ArtifactResult(
        type=request["type"],
        content=content,
        citations=[allowed[cid].model_copy(update={"citation_id": cid}) for cid in sorted(ids)],
        coverage=coverage,
        provider_metadata=metadata,
    )
