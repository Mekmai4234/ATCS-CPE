"""05 consumer contract for a trusted project-wide broker, not a local quota counter."""

import hashlib
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import Field
from youtube_backend.schemas import Schema

from .models import error


class ModelGrant(Schema):
    project_id: str = Field(min_length=1)
    credential_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_model: str = Field(min_length=1)
    returned_models: list[str] = Field(min_length=1)
    purpose: Literal["chat", "vision"]
    free_tier_verified: Literal[True]
    expires_at: float
    image_access_verified: bool = False
    max_output_tokens: int = Field(ge=128, le=32000)
    thinking_level: Literal["LOW", "MINIMAL"] | None = None


class QuotaBroker(Protocol):
    """02 supplies one broker shared by all workers/providers in the project.

    authorize binds externally verified billing, role allowlists, actual API capability,
    credential/project and alias versions. A catalog lookup alone is insufficient.
    reserve is an async context manager: atomically reserve requests/tokens/concurrency,
    debit failures/cancellation and expose record(usage, returned_model) on its lease.
    It must never retry the callback or select another model/key/provider.
    """

    def authorize(self, *, model, purpose, credential_sha256) -> ModelGrant: ...

    def reserve(self, *, grant, operation, input_tokens, output_tokens): ...


def verified_grant(broker, settings, model, purpose):
    if broker is None or not callable(getattr(broker, "authorize", None)):
        raise error("quota_pending", "Verified shared Free Tier broker is required", status=503)
    fingerprint = hashlib.sha256(settings.gemini_api_key.get_secret_value().encode()).hexdigest()
    try:
        grant = ModelGrant.model_validate(
            broker.authorize(model=model, purpose=purpose, credential_sha256=fingerprint)
        )
    except ValueError:
        raise error("quota_pending", "Verified Free Tier grant is required", status=503) from None
    if (
        grant.requested_model != model
        or grant.purpose != purpose
        or grant.credential_sha256 != fingerprint
        or grant.expires_at <= time.time()
        or (purpose == "vision" and not grant.image_access_verified)
    ):
        raise error(
            "quota_pending", "Free Tier/model verification is missing or expired", status=503
        )
    return grant


class ExecutionBroker:
    """Adapt 05's SDK scopes to 02's actual SQL reservations and durable leases.

    Binding is task-local: concurrent users never share an execution identity.
    No request JSON, fake policy or process-local counters authorize a dispatch.
    """

    def __init__(self, repository, settings):
        from youtube_backend.quota import QuotaBroker as NativeBroker

        self.native = NativeBroker(repository)
        self.settings = settings
        self.execution = ContextVar("answer_execution", default=None)

    @contextmanager
    def bind(self, context):
        context.check()
        token = self.execution.set(context)
        try:
            yield
        finally:
            self.execution.reset(token)

    def authorize(self, *, model, purpose, credential_sha256):
        context = self.execution.get()
        if context is None:
            raise error("quota_pending", "A durable execution is required", status=503)
        context.check()
        policy, grant = self.native.access(model, "generateContent", self.role(context, purpose))
        if credential_sha256 != policy.key_sha256:
            raise error(
                "quota_pending", "Answer credential differs from verified project", status=503
            )
        return ModelGrant(
            project_id=policy.project_ref,
            credential_sha256=policy.key_sha256,
            requested_model=model,
            returned_models=grant.returned_models,
            purpose=purpose,
            free_tier_verified=True,
            expires_at=policy.expires_at.timestamp(),
            image_access_verified=grant.image_capable,
            max_output_tokens=self.settings.answer_max_output_tokens,
            thinking_level="LOW" if "gemini-3" in model and "flash" in model else None,
        )

    def role(self, context, purpose):
        job = self.native.repo.check_execution(context.job_id, context.lease_token)
        return (
            "vision"
            if purpose == "vision"
            else "agent"
            if job["kind"] in {"research", "artifact"}
            else "chat"
        )

    @asynccontextmanager
    async def reserve(self, *, grant, operation, input_tokens, output_tokens):
        import httpx
        from google.genai import errors
        from youtube_backend.errors import AppError
        from youtube_backend.provider_errors import provider_error
        from youtube_backend.quota import ProviderReply

        endpoints = {"count_tokens": "countTokens", "generate_content": "generateContent"}
        if operation not in endpoints:
            raise error("quota_pending", "This provider endpoint is not approved", status=503)
        context = self.execution.get()
        if context is None:
            raise error("quota_pending", "A durable execution is required", status=503)
        self.authorize(
            model=grant.requested_model,
            purpose=grant.purpose,
            credential_sha256=grant.credential_sha256,
        )
        permit = self.native.reserve(
            context,
            model=grant.requested_model,
            endpoint=endpoints[operation],
            input_tokens=max(1, input_tokens),
            call_key=f"05:{operation}:{uuid4()}",
            role=self.role(context, grant.purpose),
        )

        class Lease:
            reply = None

            def record(self, usage, returned_model):
                count = usage.get("prompt_token_count")
                self.reply = ProviderReply(None, count, returned_model)

        lease, dispatched = Lease(), False
        try:
            self.native.dispatch(context, permit)
            dispatched = True
            yield lease
            self.native.settle(permit, reply=lease.reply or ProviderReply(None, None, None))
            context.check()
        except BaseException as exc:
            if isinstance(exc, errors.APIError):
                normalized = provider_error(exc.code)
            elif isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                normalized = provider_error(504)
            elif isinstance(exc, httpx.TransportError):
                normalized = provider_error(503)
            else:
                normalized = exc
            self.native.settle(
                permit,
                error=normalized if isinstance(normalized, AppError) else None,
                unsent=not dispatched,
            )
            if normalized is not exc:
                raise normalized from None
            raise
