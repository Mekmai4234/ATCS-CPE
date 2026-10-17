from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field
from youtube_backend.errors import AppError
from youtube_backend.schemas import ProviderMetadata, Schema


def error(code, message, *, retryable=False, status=502):
    return AppError(code, message, status, retryable)


class SearchArgs(Schema):
    query: str = Field(min_length=1, max_length=12000)
    top_k: int = Field(default=8, ge=1, le=100, strict=True)


class ReadArgs(Schema):
    video_ids: list[str] = Field(default_factory=list, max_length=100)
    cursor: str | None = Field(default=None, max_length=1000)
    limit: int = Field(default=30, ge=1, le=200, strict=True)


class CompareArgs(Schema):
    video_ids: list[str] = Field(min_length=2, max_length=100)
    instruction: str = Field(default="", max_length=4000)


class ArtifactArgs(Schema):
    type: Literal["study_plan", "quiz", "flashcards"]
    topic: str = Field(default="", max_length=4000)


class FinishArgs(Schema):
    content: str = Field(min_length=1, max_length=24000)
    citation_ids: list[str] = Field(default_factory=list, max_length=1000)


TOOL_MODELS = {
    "search_evidence": SearchArgs,
    "read_video_chunks": ReadArgs,
    "compare_videos": CompareArgs,
    "create_learning_artifact": ArtifactArgs,
    "finish_research": FinishArgs,
}

DESCRIPTIONS = {
    "search_evidence": "Search the authorized transcripts for a specific question.",
    "read_video_chunks": "Read a page of transcript chunks; follow next_cursor for coverage.",
    "compare_videos": "Ask module 05 to compare at least two authorized videos.",
    "create_learning_artifact": "Create a cited study plan, quiz or flashcards from evidence.",
    "finish_research": "Return a grounded result with known evidence IDs as citation_ids.",
}


@dataclass
class ModelReply:
    name: str
    arguments: dict
    metadata: ProviderMetadata
    native: Any = None


@dataclass
class Generated:
    content: Any
    metadata: ProviderMetadata


@dataclass
class Usage:
    requested_model: str
    provider: str = "gemini"
    returned_model: str | None = None
    latency_ms: float = 0
    usage: dict = field(default_factory=dict)

    def add(self, metadata):
        self.provider = metadata.provider
        self.returned_model = metadata.returned_model or self.returned_model
        self.latency_ms += metadata.latency_ms
        for key, value in metadata.usage.items():
            self.usage[key] = self.usage.get(key, 0) + value

    def result(self):
        return ProviderMetadata(
            provider=self.provider,
            requested_model=self.requested_model,
            returned_model=self.returned_model,
            usage=self.usage,
            latency_ms=self.latency_ms,
        )
