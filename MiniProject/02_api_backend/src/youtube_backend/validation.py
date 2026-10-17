from .errors import AppError
from .schemas import ArtifactResult, Evidence
from .urls import canonical_url


async def validate_result(result, sources, adapters, context, full_task=False):
    """Validate reference identity/scope; semantic support remains module 05/07's job."""
    context.check()
    allowed = {s.video_id: s for s in sources}
    citation_ids = [c.citation_id for c in result.citations]
    if len(set(citation_ids)) != len(citation_ids):
        raise AppError("invalid_citation", "Duplicate citation IDs", 502)
    if getattr(result, "status", None) == "answered" and not result.citations:
        raise AppError("invalid_citation", "Answered results require source citations", 502)
    if (
        isinstance(result, ArtifactResult) or getattr(result, "state", None) == "completed"
    ) and not result.citations:
        raise AppError("invalid_citation", "Completed learning outputs require citations", 502)
    evidence = await adapters.evidence(sources, [c.chunk_id for c in result.citations], context)
    normalized = [Evidence.model_validate(e) for e in evidence]
    by_id = {e.chunk_id: e for e in normalized}
    for citation in result.citations:
        source = allowed.get(citation.video_id)
        record = by_id.get(citation.chunk_id)
        if (
            not source
            or not record
            or any(
                (
                    record.video_id != citation.video_id,
                    record.transcript_version != source.transcript_version,
                    record.start_seconds != citation.start_seconds,
                    record.end_seconds != citation.end_seconds,
                )
            )
        ):
            raise AppError(
                "invalid_citation", "Citation does not match scoped source evidence", 502
            )
        citation.title = record.title
        citation.url = f"{canonical_url(record.video_id)}&t={int(record.start_seconds)}s"
        context.repository.check_evidence_bounds(record)
    coverage = result.coverage
    if coverage.expected_videos != len(sources):
        raise AppError("invalid_coverage", "Coverage does not match selected sources", 502)
    if coverage.expected_chunks is not None:
        actual_count = await adapters.inventory(sources, context)
        if (
            type(actual_count) is not int
            or actual_count < 0
            or coverage.expected_chunks != actual_count
        ):
            raise AppError(
                "invalid_coverage", "Coverage does not match indexed chunk inventory", 502
            )
    if full_task and not coverage.complete and not coverage.notes:
        raise AppError("invalid_coverage", "Partial coverage requires an explanation", 502)
    context.check()
    return result
