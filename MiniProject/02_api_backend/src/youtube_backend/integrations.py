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

    async def gemini_call(self, callback, **request):
        from .quota import QuotaBroker

        return await QuotaBroker(self.repository).call(self, callback, **request)

    async def local_inference(self, *, model, digest, operation, payload, call_key):
        from .local_inference import LocalInference

        return await LocalInference(self).call(
            model=model, digest=digest, operation=operation, payload=payload, call_key=call_key
        )

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

    def review_signals(self, signals):
        """Trusted adapter hook, kept separate from public job progress events."""
        from .answer_review import stage

        stage(self.repository, self.job_id, self.lease_token, signals)

    def checkpoint(self, key, value=None):
        """Private bounded adapter checkpoint, inherited only by a frozen replacement job."""
        import json

        from . import database as db

        if not isinstance(key, str) or not 1 <= len(key) <= 100:
            raise AppError("checkpoint_invalid", "Invalid checkpoint key", 422)
        self.check()
        with self.repository.db.write() as c:
            job = self.repository._owned(c, self.job_id, self.lease_token)
            from .local_inference import execution_identity

            pinned = job["payload"].get("execution")
            if pinned and pinned != execution_identity(self.settings):
                raise AppError("execution_changed", "Checkpoint provider configuration changed", 409)
            saved = dict(job["payload"].get("adapter_checkpoints", {}))
            if value is None:
                return saved.get(key)
            saved[key] = value
            if len(json.dumps(saved).encode()) > 512_000:
                raise AppError("checkpoint_invalid", "Checkpoint budget exceeded", 422)
            c.execute(
                db.jobs.update()
                .where(db.jobs.c.job_id == self.job_id)
                .values(payload=dict(job["payload"], adapter_checkpoints=saved))
            )
            return value


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
