"""Production local consumer: only module02's authenticated durable broker sends HTTP."""

import asyncio
import time
from uuid import uuid4

from youtube_backend.repository import digest
from youtube_backend.schemas import ProviderMetadata

from .models import Generated, GeneratedAnswer, error
from .prompts import POLICY, json_text


class TrustedLocalModel:
    requires_context = True

    def __init__(self, settings):
        self.settings = settings
        if settings.generation_provider != "ollama" or not settings.local_model:
            raise error("local_configuration", "Configure an explicit local model", status=503)

    async def generate(
        self,
        payload,
        timeout,
        *,
        context=None,
        schema=GeneratedAnswer,
        policy=POLICY,
        images=(),
        purpose="chat",
        model=None,
        output_limit=None,
    ):
        if context is None or not callable(getattr(context, "local_inference", None)):
            raise error("local_broker_required", "Trusted local execution required", status=503)
        if images or purpose == "vision" or model not in {None, self.settings.local_model}:
            raise error(
                "local_unsupported", "Local generation supports text evidence only", status=409
            )
        context.check()
        body = {
            "think": False,
            "messages": [
                {"role": "system", "content": policy},
                {"role": "user", "content": json_text(payload)},
            ],
            "format": schema.model_json_schema(),
        }
        budget = self.settings.local_context_tokens - self.settings.local_max_output_tokens - 512
        if len(json_text(body).encode()) > budget:
            raise error(
                "context_budget_exceeded", "Full local input exceeds conservative byte guard"
            )
        # The02 broker owns pinned execution identity, model-digest rechecks, global
        # concurrency, accounting, HTTP size limits and cancellation. No direct HTTP.
        key = "05-" + digest(
            [
                "local-v1",
                self.settings.model_dump(mode="json", exclude={"gemini_api_key"}),
                context.repository.check_execution(context.job_id, context.lease_token)[
                    "payload"
                ].get("sources", []),
                body,
            ]
        )
        checkpoint = getattr(context, "checkpoint", None)
        started = time.monotonic()
        saved = checkpoint(key) if callable(checkpoint) else None
        if saved is not None:
            try:
                value = schema.model_validate(saved)
            except ValueError:
                raise error("checkpoint_invalid", "Saved local output is invalid") from None
            return Generated(value, self.metadata(started, cached=True))
        async with asyncio.timeout(timeout):
            response = await context.local_inference(
                model=self.settings.local_model,
                digest=self.settings.local_model_digest,
                operation="chat",
                payload=body,
                call_key=f"05-local-{uuid4().hex}",
            )
        context.check()
        try:
            message = response["message"]
            if message.get("role") != "assistant" or message.get("tool_calls"):
                raise ValueError("Unexpected local message")
            value = schema.model_validate_json(message["content"])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise error(
                "invalid_model_output", "Local model returned invalid structured output"
            ) from None
        if callable(checkpoint):
            checkpoint(key, value.model_dump(mode="json"))
        metadata = self.metadata(started)
        metadata.usage = {
            k: response[k]
            for k in (
                "prompt_eval_count",
                "eval_count",
                "load_duration",
                "prompt_eval_duration",
                "eval_duration",
                "total_duration",
            )
            if type(response.get(k)) is int and response[k] >= 0
        }
        metadata.usage["generate_requests"] = 1
        return Generated(value, metadata)

    def metadata(self, started, *, cached=False):
        return ProviderMetadata(
            provider="ollama-cache" if cached else "ollama",
            requested_model=self.settings.local_model,
            returned_model=f"{self.settings.local_model}@sha256:{self.settings.local_model_digest}",
            latency_ms=(time.monotonic() - started) * 1000,
        )

    async def close(self):
        pass  # No owned transport; each call is owned by the durable broker.
