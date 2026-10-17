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
