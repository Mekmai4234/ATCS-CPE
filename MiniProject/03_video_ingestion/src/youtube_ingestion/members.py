"""Proposed 02/03 member boundary. No sessions, users, or membership DB is owned by 03.

This boundary is disabled unless the server injects a backend implementing the entire
contract. The existing single-user Repository is intentionally not such a backend.
"""

from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from youtube_backend.config import PROJECT_ROOT
from youtube_backend.errors import AppError
from youtube_backend.schemas import Schema, Segment, Source
from youtube_backend.urls import VIDEO_ID, normalize_url

from .errors import failure

CONTRACT_VERSION = "03-member-ingestion-proposal-v1"
REQUIRED_GUARANTEES = frozenset(
    {
        "server_session",
        "private_jobs",
        "atomic_library_admission",
        "shared_source_claim",
        "reference_safe_gc",
        "atomic_source_fence",
        "per_member_admission_and_fair_claims",
    }
)


class MemberSettings(BaseSettings):
    # Kept separate: adding fields to IngestionSettings would break 02 FullSettings.services().
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "03_video_ingestion" / ".env"),
        env_prefix="MEMBER_",
        extra="ignore",
        env_file_encoding="utf-8",
    )
    import_max_urls: int = Field(default=50, ge=1, le=500)
    pending_import_limit: int = Field(default=20, ge=1, le=10000)
    running_import_limit: int = Field(default=2, ge=1, le=100)


class MemberAdmission(Schema):
    video_id: str
    # Always a member-private ID; never the shared source worker's job ID.
    job_id: str | None = Field(default=None, min_length=1, max_length=128)
    outcome: Literal["added", "existing", "rejected"]
    status: Literal["importing", "ready", "no_transcript", "failed", "rejected"]
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,99}$")


class MemberImportItem(MemberAdmission):
    input_index: int = Field(ge=0)


class RejectedImport(Schema):
    input_index: int = Field(ge=0)
    outcome: Literal["rejected"] = "rejected"
    status: Literal["rejected"] = "rejected"
    error_code: str


class MemberImports(Schema):
    items: list[MemberImportItem | RejectedImport]


class MemberJob(Schema):
    job_id: str = Field(min_length=1, max_length=128)
    video_id: str
    state: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: Literal[
        "queued",
        "running",
        "fetching_transcript",
        "indexing",
        "ready",
        "no_transcript",
        "failed",
        "cancelled",
    ]
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,99}$")
    retryable: bool = False


class MemberSegment(Segment):
    video_id: str
    transcript_version: str
    language: str
    position: int = Field(ge=0)


class MemberTranscript(Schema):
    video_id: str
    transcript_version: str
    language: str
    source: str
    segments: list[MemberSegment]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class LibraryRemoval(Schema):
    video_id: str
    removed: bool
    # This reports a scheduled cleanup decision, never a promise of physical deletion.
    gc_scheduled: bool = False


class SourceCommand(Schema):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["ingest", "index", "read", "gc"]
    video_id: str | None = None
    generation: int | None = Field(default=None, ge=1)
    sources: tuple[Source, ...] = ()


class SourceGrant:
    """Issued by trusted 02 server composition, never parsed from an HTTP payload.

    execution.check() must revalidate the shared-worker claim or reader membership.
    execution.repository._owned() must enforce that same source/ref fence INSIDE
    04's publication/deletion transaction. A preflight check alone is insufficient.
    """

    def __init__(self, command: SourceCommand, execution: Any):
        self.command, self.execution = command, execution


class MemberBackend(Protocol):
    contract_version: str
    guarantees: frozenset[str]

    def require_member(self, context: Any) -> None:
        """Verify the server session, enabled account and CSRF where appropriate."""

    def execute_member(self, context: Any, operation: str, payload: dict, limits: dict) -> Any:
        """Reauthorize within the DB transaction, apply quotas, then return private DTOs.

        add: attach memberships, reuse/create shared work atomically and issue PRIVATE
        job IDs; ready sources require no caption/vector request. remove/cancel revoke
        only this member's interest. GC requires zero refs AND zero active dependencies.
        Reads/retry/cancel must check ownership and never reveal another user's job.
        Limits apply at durable admission/worker-claim boundaries, not in process-local
        semaphores. Shared work must not be charged once per joined member.
        """

    def authorize_source(self, context: Any, command: SourceCommand) -> SourceGrant:
        """Issue a live execution/fence for the exact shared source/read/GC operation."""


def require_backend(backend):
    guarantees = getattr(backend, "guarantees", ())
    try:
        supported = isinstance(
            guarantees, (set, frozenset, list, tuple)
        ) and REQUIRED_GUARANTEES.issubset(guarantees)
    except TypeError:
        supported = False
    if (
        backend is None
        or getattr(backend, "contract_version", None) != CONTRACT_VERSION
        or not supported
        or not all(
            callable(getattr(backend, name, None))
            for name in ("require_member", "execute_member", "authorize_source")
        )
    ):
        raise failure(
            "member_contract_unavailable",
            "Member ingestion requires the 02 session/library/job and 04 atomic source contract",
            503,
        )
    return backend


def invalid_output():
    return failure("member_contract_invalid_output", "Member backend returned invalid data")


class MemberIngestion:
    """Server-side member orchestration; no member ID or role comes from request bodies."""

    def __init__(self, backend=None, settings=None):
        self.backend = require_backend(backend)
        self.settings = settings or MemberSettings()

    def _execute(self, context, operation, payload):
        self.backend.require_member(context)
        return self.backend.execute_member(context, operation, payload, self.settings.model_dump())

    def add(self, request, context) -> MemberImports:
        from youtube_backend.schemas import ImportRequest

        self.backend.require_member(context)
        try:
            request = ImportRequest.model_validate(request)
        except ValidationError:
            raise failure(
                "validation_error", "Import request does not match the member schema", 422
            ) from None
        if len(request.urls) > self.settings.import_max_urls:
            raise failure("member_import_limit", "Too many URLs in one member request", 422)
        positions, rejected = {}, {}
        for index, url in enumerate(request.urls):
            try:
                video_id = normalize_url(url)
            except AppError as error:
                rejected[index] = RejectedImport(input_index=index, error_code=error.code)
                continue
            positions.setdefault(video_id, []).append(index)
        values = self._execute(context, "add", {"video_ids": list(positions)}) if positions else []
        try:
            admissions = [MemberAdmission.model_validate(value) for value in values]
            by_id = {value.video_id: value for value in admissions}
            if set(by_id) != set(positions) or len(admissions) != len(by_id):
                raise invalid_output()
            for value in admissions:
                if (value.outcome == "rejected") != (value.status == "rejected"):
                    raise invalid_output()
                if value.outcome == "rejected":
                    if value.job_id is not None or not value.error_code:
                        raise invalid_output()
                else:
                    if not value.job_id:
                        raise invalid_output()
                    failed = value.status in {"failed", "no_transcript"}
                    if failed != (value.error_code is not None):
                        raise invalid_output()
                for index in positions[value.video_id]:
                    rejected[index] = MemberImportItem(input_index=index, **value.model_dump())
            return MemberImports(items=[rejected[i] for i in range(len(request.urls))])
        except (ValidationError, TypeError, AttributeError):
            raise invalid_output() from None

    def job(self, job_id, context, *, operation="job") -> MemberJob:
        self.backend.require_member(context)
        if operation not in {"job", "retry", "cancel"}:
            raise failure("invalid_operation", "Unsupported member job operation", 422)
        if not isinstance(job_id, str) or not 1 <= len(job_id) <= 128:
            raise failure("invalid_job_id", "Provide a private member job ID", 422)
        value = self._execute(context, operation, {"job_id": job_id})
        try:
            result = MemberJob.model_validate(value)
            # Retry may issue a new member-private job. Ordinary reads/cancel must match.
            if operation != "retry" and result.job_id != job_id:
                raise invalid_output()
            return result
        except ValidationError:
            raise invalid_output() from None

    def transcript(self, video_id, context, *, limit=100, offset=0) -> MemberTranscript:
        self.backend.require_member(context)
        self._video_id(video_id)
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise failure("invalid_limit", "Invalid member transcript pagination", 422)
        value = self._execute(
            context, "transcript", dict(video_id=video_id, limit=limit, offset=offset)
        )
        try:
            result = MemberTranscript.model_validate(value)
            if (
                result.video_id != video_id
                or result.limit != limit
                or result.offset != offset
                or len(result.segments) > limit
                or offset + len(result.segments) > max(offset, result.total)
                or any(
                    s.video_id != video_id
                    or s.transcript_version != result.transcript_version
                    or s.language != result.language
                    for s in result.segments
                )
            ):
                raise invalid_output()
            return result
        except ValidationError:
            raise invalid_output() from None

    def remove(self, video_id, context) -> LibraryRemoval:
        self.backend.require_member(context)
        self._video_id(video_id)
        value = self._execute(context, "remove", {"video_id": video_id})
        try:
            result = LibraryRemoval.model_validate(value)
            if result.video_id != video_id:
                raise invalid_output()
            return result
        except ValidationError:
            raise invalid_output() from None

    @staticmethod
    def _video_id(video_id):
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            raise failure("invalid_video_id", "Provide a valid YouTube video ID", 422)
