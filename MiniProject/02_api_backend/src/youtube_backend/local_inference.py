"""Private Ollama transport. No cloud fallback, model downloads or public proxy."""

import asyncio
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import sqlalchemy as sa

from . import database as db
from .errors import AppError


def execution_identity(settings):
    return {
        "provider": settings.generation_provider,
        "model": settings.local_model
        if settings.generation_provider == "ollama"
        else settings.llm_model,
        "version": settings.local_model_digest
        if settings.generation_provider == "ollama"
        else None,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_version": settings.local_embedding_digest
        if settings.embedding_provider == "ollama"
        else None,
    }


def private_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname
        not in {"127.0.0.1", "localhost", "::1", "ollama", "host.docker.internal"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise AppError("local_configuration", "Local inference requires a private service URL", 503)
    return value.rstrip("/")


class LocalInference:
    def __init__(self, context, *, transport=None):
        self.context = context
        self.repo = context.repository
        self.settings = context.settings
        self.transport = transport

    async def _json(self, client, method, path, **kwargs):
        async with client.stream(method, path, **kwargs) as response:
            if response.status_code != 200:
                raise AppError(
                    "local_unavailable", "Local model service rejected the request", 503, True
                )
            data = bytearray()
            async for block in response.aiter_bytes():
                data.extend(block)
                if len(data) > 2_000_000:
                    raise AppError("local_invalid_response", "Local response exceeds limit", 502)
            try:
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError
                return value
            except (ValueError, TypeError):
                raise AppError("local_invalid_response", "Invalid local response", 502) from None

    async def call(self, *, model, digest, operation, payload, call_key):
        self.context.check()
        if operation not in {"chat", "embed"} or not isinstance(payload, dict):
            raise AppError("local_configuration", "Unsupported local operation", 422)
        if not isinstance(call_key, str) or not 0 < len(call_key) <= 160:
            raise AppError("local_configuration", "A bounded call key is required", 422)
        settings = self.settings
        expected = (
            (settings.local_model, settings.local_model_digest)
            if operation == "chat"
            else (settings.local_embedding_model, settings.local_embedding_digest)
        )
        enabled = (
            settings.generation_provider == "ollama"
            if operation == "chat"
            else (settings.embedding_provider == "ollama")
        )
        if (
            not enabled
            or (model, digest) != expected
            or not model
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise AppError("local_configuration", "Pin an enabled local model and digest", 503)
        forbidden = {"model", "stream", "keep_alive", "options", "truncate"}
        if forbidden.intersection(payload) or len(json.dumps(payload).encode()) > 256_000:
            raise AppError("local_input_too_large", "Invalid or oversized local request", 422)
        identity = execution_identity(settings)
        table = db.v2["reservations"]
        permit = str(uuid4())
        key = hashlib.sha256(call_key.encode()).hexdigest()
        now = time.time()
        # Reuse durable attempt accounting in a distinct local project namespace.
        # It never enters a Gemini project's quota/circuit or policy pin.
        with self.repo.db.write() as c:
            job = self.repo._owned(c, self.context.job_id, self.context.lease_token)
            if not job["owner_id"]:
                raise AppError("authentication_required", "Local execution needs a member", 401)
            if job["payload"].get("execution") != identity:
                raise AppError(
                    "execution_changed", "Provider configuration changed; create new work", 409
                )
            if c.scalar(
                sa.select(table.c.reservation_id).where(
                    table.c.project == "local:ollama",
                    table.c.job_id == job["job_id"],
                    table.c.lease_token == self.context.lease_token,
                    table.c.call_key == key,
                )
            ):
                raise AppError("reservation_used", "Local call key was already attempted", 409)
            active = c.scalar(
                sa.select(sa.func.count())
                .select_from(table)
                .where(
                    table.c.project == "local:ollama",
                    table.c.state == "sent",
                    table.c.expires_at > now,
                )
            )
            if active >= settings.local_max_concurrent:
                raise AppError(
                    "local_busy",
                    "Local inference capacity is occupied",
                    429,
                    True,
                    retry_after_seconds=5,
                    retry_time_source="estimate",
                )
            c.execute(
                table.insert().values(
                    reservation_id=permit,
                    project="local:ollama",
                    policy_digest=digest,
                    bucket="local",
                    model=model,
                    endpoint=operation,
                    role="local",
                    owner_id=job["owner_id"],
                    job_id=job["job_id"],
                    lease_token=self.context.lease_token,
                    call_key=key,
                    state="sent",
                    tokens=0,
                    created_at=now,
                    expires_at=min(job["deadline_at"], now + settings.llm_timeout_seconds),
                    returned_allowlist=[model],
                )
            )
        state = "uncertain"
        try:
            async with asyncio.timeout(
                min(self.context.remaining_seconds, settings.llm_timeout_seconds)
            ):
                async with httpx.AsyncClient(
                    base_url=private_url(settings.local_base_url),
                    transport=self.transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=settings.llm_timeout_seconds,
                ) as client:
                    tags = await self._json(client, "GET", "/api/tags")
                    if not any(
                        item.get("name") == model and item.get("digest") == digest
                        for item in tags.get("models", [])
                        if isinstance(item, dict)
                    ):
                        state = "cancelled"  # No prompt was sent.
                        raise AppError(
                            "local_model_changed", "Pinned local model is unavailable", 503
                        )
                    self.context.check()
                    body = dict(payload, model=model, keep_alive="5m")
                    if operation == "chat":
                        body.update(
                            stream=False,
                            options={
                                "num_ctx": settings.local_context_tokens,
                                "num_predict": settings.local_max_output_tokens,
                                "temperature": 0,
                            },
                        )
                    else:
                        body["truncate"] = False
                    value = await self._json(client, "POST", "/api/" + operation, json=body)
                    if value.get("model") != model or (
                        operation == "chat"
                        and (value.get("done") is not True or value.get("done_reason") != "stop")
                    ):
                        raise AppError(
                            "local_invalid_response", "Incomplete or mismatched model output", 502
                        )
                    # Alias mutation during execution invalidates the result, too.
                    tags = await self._json(client, "GET", "/api/tags")
                    if not any(
                        item.get("name") == model and item.get("digest") == digest
                        for item in tags.get("models", [])
                        if isinstance(item, dict)
                    ):
                        raise AppError(
                            "local_model_changed", "Local model changed during execution", 503
                        )
                    self.context.check()
                    state = "completed"
                    return value
        except (httpx.TimeoutException, TimeoutError):
            raise AppError(
                "local_timeout", "Local inference exceeded its deadline", 504, True
            ) from None
        except httpx.TransportError:
            raise AppError(
                "local_unavailable", "Local model service is unavailable", 503, True
            ) from None
        finally:
            with self.repo.db.write() as c:
                c.execute(
                    table.update().where(table.c.reservation_id == permit).values(state=state)
                )
