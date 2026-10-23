"""Typed boundaries owned jointly with 03-06. No live model calls in module 02."""

import importlib
import time
from dataclasses import dataclass
from typing import Protocol

from .config import Settings
from .errors import AppError
from .repository import Repository
from .schemas import (
    AnswerResult,
    ArtifactResult,
    Evidence,
    IndexReceipt,
    ProgressEvent,
    ResearchResult,
    Source,
    TranscriptResult,
)


@dataclass
class ExecutionContext:
    repository: Repository
    job_id: str
    lease_token: str
    deadline_at: float
    settings: Settings

    @property
    def user_id(self):
        """Trusted durable owner, never a client-supplied request/payload field."""
        return self.repository.check_execution(self.job_id, self.lease_token)["owner_id"]

    def authorize_sources(self, sources):
        job = self.repository.check_execution(self.job_id, self.lease_token)
        allowed = job["payload"].get("sources", [])
        if not sources or any(source.model_dump() not in allowed for source in sources):
            raise AppError("invalid_scope", "Sources exceed this execution's authorized scope", 403)
        return tuple(sources)

    def check(self):
        self.repository.check_execution(self.job_id, self.lease_token)
        if time.time() >= self.deadline_at:
            raise AppError("task_timeout", "Task exceeded its deadline", 504, True)

    @property
    def remaining_seconds(self):
        return max(0.0, self.deadline_at - time.time())

    def event(self, event: ProgressEvent):
        self.check()
        self.repository.add_event(self.job_id, self.lease_token, event.model_dump())


class Adapters(Protocol):
    """All methods must be async, cancellable, bounded, and idempotent where mutating.

    Index writes MUST use generation/version namespaces and fence stale execution tokens.
    Check context before effects and atomically before publication. Delete only generations
    <= the supplied generation. Module 04 must enforce these at its persistence boundary.
    The coordinator alone cannot roll back an external vector store write.
    """

    async def ingest(self, video_id: str, context: ExecutionContext) -> TranscriptResult: ...

    async def index(
        self, source: Source, transcript: TranscriptResult, context: ExecutionContext
    ) -> IndexReceipt: ...

    async def delete(self, video_id: str, generation: int, context: ExecutionContext) -> None: ...

    async def evidence(
        self, sources: list[Source], chunk_ids: list[str], context: ExecutionContext
    ) -> list[Evidence]: ...

    async def inventory(self, sources: list[Source], context: ExecutionContext) -> int: ...

    async def answer(
        self, request: dict, sources: list[Source], history: list[dict], context: ExecutionContext
    ) -> AnswerResult: ...

    async def analyze(
        self, request: dict, sources: list[Source], context: ExecutionContext
    ) -> AnswerResult: ...

    async def research(
        self, request: dict, sources: list[Source], context: ExecutionContext
    ) -> ResearchResult: ...

    async def artifact(
        self, request: dict, sources: list[Source], context: ExecutionContext
    ) -> ArtifactResult: ...


class UnavailableAdapters:
    async def _missing(self, *args, **kwargs):
        raise AppError(
            "dependency_unavailable",
            "Modules 03-06 are not connected; configure an adapter",
            503,
            True,
        )

    ingest = index = delete = evidence = inventory = answer = analyze = research = artifact = (
        _missing
    )


def load_adapters(settings: Settings, repository: Repository) -> Adapters:
    if settings.adapter_mode == "fixture":
        from .fixture_adapter import FixtureAdapters

        return FixtureAdapters(repository, settings)
    if settings.adapter_mode == "custom":
        # Trusted server configuration only; never accept a module path in an HTTP request.
        module, name = settings.adapter_factory.split(":", 1)
        factory = getattr(importlib.import_module(module), name)
        return factory(settings=settings, repository=repository)
    return UnavailableAdapters()
