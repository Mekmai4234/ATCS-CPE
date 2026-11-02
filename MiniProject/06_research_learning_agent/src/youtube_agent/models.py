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
    limit: int = Field(default=100, ge=1, le=200, strict=True)


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
    "create_learning_artifact": (
        "Create a cited study plan, quiz or flashcards from evidence. Use ONLY when the "
        "user's goal explicitly asks for a study plan, quiz, flashcards or practice; the "
        "level/days fields alone are not a request. Otherwise gather evidence and answer "
        "the goal directly."
    ),
    "finish_research": (
        "Return the final answer to the goal as plain text without Markdown (no ** or #). "
        "Give concrete points taken from the evidence and put every evidence ID you rely on "
        "in citation_ids. If a learning artifact was created, mention it in one sentence "
        "instead of repeating its content."
    ),
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
    fallback_from: str | None = None

    def add(self, metadata):
        self.provider = metadata.provider
        if getattr(metadata, "fallback_from", None):
            # Report the model that actually answered, not only the configured primary.
            self.fallback_from = metadata.fallback_from
            self.requested_model = metadata.requested_model
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
            fallback_from=self.fallback_from,
        )
