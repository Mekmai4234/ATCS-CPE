import hashlib
import json
from typing import Literal

from pydantic import Field
from youtube_backend.schemas import Evidence, Schema, Source


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def source_key(source: Source):
    return digest(source.model_dump())


class Chunk(Evidence):
    schema_version: Literal[2] = 2
    token_count_kind: Literal["utf8-byte-budget-v1"] = "utf8-byte-budget-v1"
    generation: int = Field(ge=1)
    embedding_version: str
    segment_ids: list[str] = Field(min_length=1)
    ordinal: int = Field(ge=0)
    token_count: int = Field(gt=0)
    canonical_url: str

    def evidence(self):
        return Evidence.model_validate(self.model_dump(include=set(Evidence.model_fields)))


def transcript_source(snapshot):
    """Unwrap 02's explicit v2 transcript snapshot; never synthesize speech/version."""
    from youtube_backend.evidence_v2 import SourceSnapshotV2

    value = SourceSnapshotV2.model_validate(snapshot)
    if value.kind != "transcript":
        raise ValueError("A transcript snapshot is required")
    return Source(
        video_id=value.video_id,
        generation=value.generation,
        transcript_version=value.evidence_version,
    )


class SearchHit(Schema):
    chunk: Chunk
    ranking_score: float


class CoverageInventory(Schema):
    expected_videos: int
    available_videos: int
    expected_chunks: int | None
    available_chunks: int
    missing_sources: list[Source]
    complete: bool


class ChunkPage(Schema):
    items: list[Chunk]
    total: int
    next_cursor: str | None
    inventory: CoverageInventory
