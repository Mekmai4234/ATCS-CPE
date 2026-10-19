from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator
from youtube_backend.errors import AppError
from youtube_backend.schemas import ProviderMetadata, Schema


def error(code, message, *, status=502, retryable=False):
    return AppError(code, message, status, retryable)


class Statement(Schema):
    text: str = Field(min_length=1, max_length=12000)
    citation_ids: list[str] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique(self):
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("Duplicate citation IDs")
        return self


class GeneratedAnswer(Schema):
    status: Literal["answered", "insufficient_evidence"]
    statements: list[Statement] = Field(default_factory=list, max_length=100)
    message: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "answered" and (not self.statements or self.message):
            raise ValueError("Answers require cited statements and no uncited message")
        if self.status == "insufficient_evidence" and (self.statements or not self.message):
            raise ValueError("Insufficient evidence requires a message without factual statements")
        return self


@dataclass
class Generated:
    content: GeneratedAnswer
    metadata: ProviderMetadata
