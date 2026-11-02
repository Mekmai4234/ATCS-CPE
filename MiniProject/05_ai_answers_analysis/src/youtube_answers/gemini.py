"""One async, bounded count+generate attempt. Module 02 owns job retries."""

import asyncio
import re
import time

import httpx
from google import genai
from google.genai import errors, types
from youtube_backend.errors import AppError
from youtube_backend.schemas import ProviderMetadata

from .models import Generated, GeneratedAnswer, error
from .prompts import POLICY, json_text, provider_response_schema
from .quota import verified_grant
from .timing import provider_call

# Per-model bucket exhaustion: another approved model in the same project may answer.
RATE_LIMITED = {"quota_wait", "provider_rate_limited", "generation_rate_limited"}
# A fallback missing from the operator policy is skipped, not reported as the failure.
UNAPPROVED_FALLBACK = {"free_model_unverified"}


class GeminiModel:
    def __init__(self, settings, *, client=None, broker=None):
        self.settings = settings
        self.broker = broker
        self._client = client
        self._http = None

    @property
    def client(self):
        if self._client is not None:
            return self._client
        settings = self.settings
        if not settings.gemini_api_key.get_secret_value():
            raise error("generation_unavailable", "GEMINI_API_KEY is required", status=503)
        self._http = httpx.AsyncClient()
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=int(settings.llm_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
                httpx_async_client=self._http,
            ),
        )
        return self._client

    def grant(self, model, purpose):
        return verified_grant(self.broker, self.settings, model, purpose)

    def _recheck(self, grant):
        current = self.grant(grant.requested_model, grant.purpose)
        if current.model_dump(exclude={"expires_at"}) != grant.model_dump(exclude={"expires_at"}):
            raise error("quota_pending", "Verified model/project policy changed", status=503)

    async def generate(self, payload, timeout, *, model=None, **options):
        """Try LLM_MODEL, then LLM_FALLBACK_MODELS when only its bucket is limited.

        Every attempt still uses the same verified project/key and the broker's
        reservations. A caller-pinned model or a vision request never falls back.
        """
        if model or options.get("purpose", "chat") != "chat":
            return await self._attempt(
                payload, timeout, model=model or self.settings.llm_model, **options
            )
        chain = self.settings.model_chain()
        deadline = time.monotonic() + timeout
        limited = None
        for index, candidate in enumerate(chain):
            remaining = deadline - time.monotonic()
            if index and remaining < 1:
                break
            try:
                return await self._attempt(payload, remaining, model=candidate, **options)
            except AppError as exc:
                if index and exc.code in UNAPPROVED_FALLBACK:
                    continue
                if exc.code not in RATE_LIMITED:
                    raise
                limited = limited or exc
        raise limited

    async def _attempt(
        self,
        payload,
        timeout,
        *,
        schema=GeneratedAnswer,
        policy=POLICY,
        images=(),
        purpose="chat",
        model,
        output_limit=None,
    ):
        grant = self.grant(model, purpose)
        if images and purpose != "vision":
            raise error("invalid_scope", "Images require an authorized vision grant")
        if len(images) > 1 or any(
            len(data) > self.settings.vision_max_image_bytes for data, _ in images
        ):
            raise error("context_budget_exceeded", "Inline image exceeds the bounded request")
        config = types.GenerateContentConfig(
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            system_instruction=policy,
            max_output_tokens=min(
                self.settings.answer_max_output_tokens,
                grant.max_output_tokens,
                output_limit or self.settings.answer_max_output_tokens,
            ),
            response_mime_type="application/json",
            response_json_schema=provider_response_schema(
                schema,
                citation_ids=[
                    cid
                    for item in payload.get("untrusted_evidence", [])
                    for cid in item.get("citation_ids", [])
                ],
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        # Gemini 3 Flash shares max_output_tokens between thinking and answer JSON.
        # Its default thinking can consume this bounded answer budget before the
        # first statement is complete. Other model families keep their own defaults.
        if grant.thinking_level and re.match(
            r"^(?:models/)?gemini-3(?:\.\d+)?-flash(?:-|$)", model
        ):
            config.thinking_config = types.ThinkingConfig(thinking_level=grant.thinking_level)
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text=json_text(payload)),
                    *[types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images],
                ],
            )
        ]
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout):
                async with self.broker.reserve(
                    grant=grant,
                    operation="count_tokens",
                    input_tokens=self.settings.max_context_tokens,
                    output_tokens=0,
                ) as count_lease:
                    self._recheck(grant)
                    provider_call("count_tokens")
                    count = await self.client.aio.models.count_tokens(
                        model=model,
                        contents=contents,
                        config=types.CountTokensConfig(
                            http_options=types.HttpOptions(
                                retry_options=types.HttpRetryOptions(attempts=1),
                            )
                        ),
                    )
                    count_lease.record({"prompt_token_count": count.total_tokens}, None)
                if type(count.total_tokens) is not int or count.total_tokens <= 0:
                    raise error("invalid_token_count", "Gemini returned an invalid token count")
                # countTokens cannot count GenerateContentConfig on the Developer API.
                # Reserve serialized config bytes plus framing instead of claiming exactness.
                allowance = len(config.model_dump_json(exclude_none=True).encode("utf-8")) + 256
                if count.total_tokens + allowance > self.settings.max_context_tokens:
                    raise error("context_budget_exceeded", "Model input exceeds context budget")
                async with self.broker.reserve(
                    grant=grant,
                    operation="generate_content",
                    input_tokens=count.total_tokens + allowance,
                    output_tokens=config.max_output_tokens,
                ) as lease:
                    self._recheck(grant)
                    provider_call("generate_content")
                    response = await self.client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    lease.record(
                        response.usage_metadata.model_dump() if response.usage_metadata else {},
                        response.model_version,
                    )
            self._recheck(grant)
            if len(response.candidates or []) != 1:
                raise error("invalid_model_output", "Gemini returned no single usable candidate")
            candidate = response.candidates[0]
            if str(candidate.finish_reason) in {"MAX_TOKENS", "FinishReason.MAX_TOKENS"}:
                raise error(
                    "generation_output_truncated",
                    "Gemini exhausted the output token budget before completing the answer",
                )
            if str(candidate.finish_reason) not in {"STOP", "FinishReason.STOP"}:
                raise error("invalid_model_output", "Gemini output was blocked or truncated")
            if candidate.content is None or any(
                p.function_call for p in candidate.content.parts or []
            ):
                raise error("invalid_model_output", "Unexpected Gemini content")
            try:
                content = schema.model_validate_json(response.text)
            except (ValueError, TypeError):
                raise error("invalid_model_output", "Gemini returned invalid answer JSON") from None
            if response.model_version not in grant.returned_models:
                raise error(
                    "quota_pending", "Returned model requires Free Tier re-verification", status=503
                )
            usage = response.usage_metadata
            return Generated(
                content,
                ProviderMetadata(
                    provider="gemini",
                    requested_model=model,
                    returned_model=response.model_version,
                    usage={
                        k: v
                        for k, v in (usage.model_dump() if usage else {}).items()
                        if type(v) is int and v >= 0
                    },
                    latency_ms=(time.monotonic() - started) * 1000,
                ),
            )
        except (httpx.TimeoutException, TimeoutError):
            raise error(
                "generation_timeout",
                "Gemini request exceeded its deadline",
                status=504,
                retryable=True,
            ) from None
        except httpx.TransportError:
            raise error(
                "generation_unavailable",
                "Gemini transport is unavailable",
                status=503,
                retryable=True,
            ) from None
        except errors.APIError as exc:
            transient = exc.code in {408, 429} or (isinstance(exc.code, int) and exc.code >= 500)
            if exc.code == 503:
                raise error(
                    "generation_provider_busy",
                    "Gemini is temporarily unavailable; try again later",
                    status=503,
                    retryable=True,
                ) from None
            if exc.code == 429:
                raise error(
                    "generation_rate_limited",
                    "Gemini request or token quota is temporarily limiting this request",
                    status=503,
                    retryable=True,
                ) from None
            raise error(
                "generation_provider_error",
                "Gemini rejected the request",
                status=503 if transient else 502,
                retryable=transient,
            ) from None

    async def close(self):
        if self._client is None:
            return
        try:
            await self._client.aio.aclose()
            self._client.close()
        finally:
            if self._http is not None:
                await self._http.aclose()

    async def check_access(self, timeout):
        """Read account-visible model metadata; this does not establish generation access."""
        try:
            async with asyncio.timeout(timeout):
                grant = self.grant(self.settings.llm_model, "chat")
                async with self.broker.reserve(
                    grant=grant,
                    operation="get_model",
                    input_tokens=0,
                    output_tokens=0,
                ):
                    self._recheck(grant)
                    model = await self.client.aio.models.get(
                        model=self.settings.llm_model,
                        config=types.GetModelConfig(
                            http_options=types.HttpOptions(
                                retry_options=types.HttpRetryOptions(attempts=1),
                            )
                        ),
                    )
            return {
                "requested_model": self.settings.llm_model,
                "catalog_name": model.name,
                "supported_actions": model.supported_actions or [],
                "generation_verified": False,
            }
        except (httpx.TimeoutException, TimeoutError):
            raise error("model_check_timeout", "Model lookup exceeded its deadline") from None
        except (errors.APIError, httpx.TransportError):
            raise error(
                "model_check_failed", "Model lookup was not available to this account"
            ) from None
