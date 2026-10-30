from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Scope(Schema):
    video_ids: list[str] = Field(min_length=1, max_length=100)
    channel_ids: list[str] = Field(default_factory=list, max_length=100)
    playlist_ids: list[str] = Field(default_factory=list, max_length=100)
    date_from: date | None = None
    date_to: date | None = None

    @field_validator("video_ids", "channel_ids", "playlist_ids")
    @classmethod
    def unique_ids(cls, values):
        if any(not v or len(v) > 200 for v in values):
            raise ValueError("IDs must be nonempty and at most 200 characters")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def date_order(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class ImportRequest(Schema):
    urls: list[str] = Field(min_length=1, max_length=500)


class ChatRequest(Schema):
    question: str = Field(min_length=1, max_length=12000)
    conversation_id: str | None = Field(default=None, max_length=100)
    scope: Scope


class AnalysisRequest(Schema):
    type: Literal["summary", "compare"]
    scope: Scope
    instruction: str = Field(default="", max_length=4000)


class ResearchRequest(Schema):
    goal: str = Field(min_length=1, max_length=12000)
    scope: Scope
    level: str = Field(default="beginner", min_length=1, max_length=100)
    days: int = Field(default=7, ge=1, le=90)


class ArtifactRequest(Schema):
    type: Literal["study_plan", "quiz", "flashcards"]
    scope: Scope
    topic: str = Field(default="", max_length=4000)
    level: str = Field(default="beginner", min_length=1, max_length=100)
    days: int = Field(default=7, ge=1, le=90)


class Segment(Schema):
    segment_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)


class TranscriptResult(Schema):
    video_id: str
    title: str | None = Field(default=None, min_length=1)
    channel_id: str | None = None
    channel_title: str | None = None
    thumbnail_url: str | None = None
    published_at: date | None = None
    language: str = Field(min_length=1, max_length=30)
    source: str = Field(min_length=1, max_length=100)
    segments: list[Segment] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_segments(self):
        ids = [s.segment_id for s in self.segments]
        starts = [s.start_seconds for s in self.segments]
        if len(ids) != len(set(ids)) or starts != sorted(starts):
            raise ValueError("Segments must have unique IDs and ordered start times")
        return self


class Source(Schema):
    video_id: str
    generation: int = Field(ge=1)
    transcript_version: str


class IndexReceipt(Schema):
    source: Source
    chunk_count: int = Field(gt=0)
    complete: Literal[True]


class Evidence(Schema):
    chunk_id: str = Field(min_length=1)
    video_id: str
    transcript_version: str
    title: str
    text: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def interval(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Invalid evidence interval")
        return self


class Citation(Schema):
    citation_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    video_id: str
    title: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    url: str = ""
    kind: Literal["transcript", "video"] = "transcript"
    observation_cache_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class Coverage(Schema):
    expected_videos: int = Field(ge=0)
    processed_videos: int = Field(ge=0)
    expected_chunks: int | None = Field(default=None, ge=0)
    processed_chunks: int | None = Field(default=None, ge=0)
    complete: bool = False
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def counts(self):
        if self.processed_videos > self.expected_videos:
            raise ValueError("Invalid video coverage")
        if (self.expected_chunks is None) != (self.processed_chunks is None):
            raise ValueError("Both chunk counts must be supplied together")
        if self.expected_chunks is not None and self.processed_chunks > self.expected_chunks:
            raise ValueError("Invalid chunk coverage")
        if self.complete and (
            self.processed_videos != self.expected_videos
            or self.expected_chunks is None
            or self.processed_chunks != self.expected_chunks
        ):
            raise ValueError("Complete coverage requires matching measured counts")
        return self


class ProviderMetadata(Schema):
    provider: str
    requested_model: str
    returned_model: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: float = Field(ge=0)


class AnswerResult(Schema):
    status: Literal["answered", "insufficient_evidence"]
    answer: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    coverage: Coverage
    provider_metadata: ProviderMetadata


class StudyDay(Schema):
    day: int = Field(ge=1, le=90)
    topic: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)


class StudyPlanContent(Schema):
    days: list[StudyDay] = Field(min_length=1, max_length=90)


class QuizQuestion(Schema):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)


class QuizContent(Schema):
    questions: list[QuizQuestion] = Field(min_length=1, max_length=100)


class Flashcard(Schema):
    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)


class FlashcardsContent(Schema):
    cards: list[Flashcard] = Field(min_length=1, max_length=100)


class ArtifactResult(Schema):
    type: Literal["study_plan", "quiz", "flashcards"]
    content: StudyPlanContent | QuizContent | FlashcardsContent
    citations: list[Citation] = Field(default_factory=list)
    coverage: Coverage
    provider_metadata: ProviderMetadata

    @model_validator(mode="after")
    def validate_content(self):
        expected = {
            "study_plan": StudyPlanContent,
            "quiz": QuizContent,
            "flashcards": FlashcardsContent,
        }
        if not isinstance(self.content, expected[self.type]):
            raise ValueError("Artifact content must match its type")
        items = getattr(
            self.content,
            {"study_plan": "days", "quiz": "questions", "flashcards": "cards"}[self.type],
        )
        known = {c.citation_id for c in self.citations}
        if any(set(item.citations) - known for item in items):
            raise ValueError("Artifact item references unknown citations")
        if self.type == "study_plan":
            days = [item.day for item in items]
            if days != list(range(1, len(days) + 1)):
                raise ValueError("Study days must be consecutive from day one")
        return self


class ResearchResult(Schema):
    state: Literal["completed", "partial"]
    content: str = Field(min_length=1)
    artifacts: list[ArtifactResult] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    coverage: Coverage
    provider_metadata: ProviderMetadata


class ProgressEvent(Schema):
    step: int = Field(ge=0)
    tool_name: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2000)


class ErrorDetail(Schema):
    code: str
    message: str
    retryable: bool
    request_id: str
    job_id: str | None = None


class ErrorResponse(Schema):
    error: ErrorDetail


class Accepted(Schema):
    job_id: str
    state: str
    run_id: str | None = None


class ChatResponse(AnswerResult):
    conversation_id: str
    job_id: str
    mode: str
    sources_available: bool = True


class ImportItem(Schema):
    input_index: int
    outcome: Literal["accepted", "existing", "rejected"]
    video_id: str | None = None
    job_id: str | None = None
    error_code: str | None = None


class ImportResponse(Schema):
    jobs: list[ImportItem]
    mode: str


class JobResponse(Schema):
    wait: dict[str, Any] | None = None
    job_id: str
    request_id: str
    kind: str
    video_id: str | None
    conversation_id: str | None
    state: str
    stage: str
    attempt_count: int
    max_attempts: int
    error_code: str | None
    retryable: bool
    cancel_requested: bool
    result: dict[str, Any] | None
    created_at: str
    updated_at: str
    available_at: str
    mode: str
    run_id: str | None = None
    sources_available: bool | None = None


class VideoRecord(Schema):
    video_id: str
    canonical_url: str
    title: str | None
    channel_id: str | None
    channel_title: str | None
    thumbnail_url: str | None
    published_at: str | None
    status: str
    generation: int
    transcript_version: str | None
    indexed_version: str | None
    created_at: str
    updated_at: str


class VideoList(Schema):
    items: list[VideoRecord]
    total: int
    limit: int
    offset: int
    mode: str


class TranscriptResponse(Schema):
    video_id: str
    transcript_version: str
    language: str
    source: str
    segments: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class ConversationResponse(Schema):
    conversation_id: str
    messages: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
    scope: Scope | None = None


class ConversationSummary(Schema):
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    video_ids: list[str]


class ConversationList(Schema):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int
