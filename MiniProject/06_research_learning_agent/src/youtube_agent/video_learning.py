"""Learning artifacts from explicitly labelled native-video observations, never fake speech."""

from dataclasses import dataclass

from youtube_backend.schemas import ArtifactResult

from .models import error


@dataclass
class VideoLearningEvidence:
    citation: object

    def model_dump(self):
        return dict(
            evidence_id=self.citation.chunk_id,
            kind="video_observation",
            text=self.citation.title,
            video_id=self.citation.video_id,
            start_seconds=self.citation.start_seconds,
            end_seconds=self.citation.end_seconds,
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
    evidence = [VideoLearningEvidence(c) for c in native.citations]
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
    allowed = {c.chunk_id: c for c in native.citations}
    if not ids.issubset(allowed) or not ids:
        raise error("invalid_citation", "Video artifact cites unknown observations")
    if request["type"] == "study_plan" and len(items) != request["days"]:
        raise error("invalid_artifact", "Study plan day count does not match request")
    metadata = generated.metadata.model_copy(deep=True)
    for key, count in native.provider_metadata.usage.items():
        metadata.usage[key] = metadata.usage.get(key, 0) + count
    metadata.latency_ms += native.provider_metadata.latency_ms
    return ArtifactResult(
        type=request["type"],
        content=content,
        citations=[allowed[cid].model_copy(update={"citation_id": cid}) for cid in sorted(ids)],
        coverage=native.coverage,
        provider_metadata=metadata,
    )
