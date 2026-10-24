"""One async, bounded count+generate attempt. Module 02 owns job retries."""

import asyncio
import re
import time

import httpx
from google import genai
from google.genai import errors, types
from youtube_backend.schemas import ProviderMetadata

from .models import Generated, GeneratedAnswer, error
from .prompts import POLICY, json_text


def provider_response_schema():
    """Keep high-cardinality array bounds out of Gemini's constrained decoder.

    The nested 100 statements / 1000 citation IDs limits can make generateContent
    reject this otherwise valid schema with INVALID_ARGUMENT. They are still enforced
    by GeneratedAnswer when validating the actual response, before it is published.
    """

    def compact(value):
        if isinstance(value, dict):
            return {key: compact(item) for key, item in value.items() if key != "maxItems"}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    return compact(GeneratedAnswer.model_json_schema())


class GeminiModel:
    def __init__(self, settings, *, client=None):
        self.settings = settings
        if client is None and not settings.gemini_api_key.get_secret_value():
            raise error("generation_unavailable", "GEMINI_API_KEY is required", status=503)
        self._http = httpx.AsyncClient() if client is None else None
        self.client = client or genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=int(settings.llm_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
                httpx_async_client=self._http,
            ),
        )

    async def generate(self, payload, timeout):
        config = types.GenerateContentConfig(
            system_instruction=POLICY,
            max_output_tokens=self.settings.answer_max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=provider_response_schema(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        # Gemini 3 Flash shares max_output_tokens between thinking and answer JSON.
        # Its default thinking can consume this bounded answer budget before the
        # first statement is complete. Other model families keep their own defaults.
        if re.match(r"^(?:models/)?gemini-3(?:\.\d+)?-flash(?:-|$)", self.settings.llm_model):
            config.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
        contents = [types.Content(role="user", parts=[types.Part(text=json_text(payload))])]
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout):
                count = await self.client.aio.models.count_tokens(
                    model=self.settings.llm_model, contents=contents
                )
                if type(count.total_tokens) is not int or count.total_tokens <= 0:
                    raise error("invalid_token_count", "Gemini returned an invalid token count")
                # countTokens cannot count GenerateContentConfig on the Developer API.
                # Reserve serialized config bytes plus framing instead of claiming exactness.
                allowance = len(config.model_dump_json(exclude_none=True).encode("utf-8")) + 256
                if count.total_tokens + allowance > self.settings.max_context_tokens:
                    raise error("context_budget_exceeded", "Model input exceeds context budget")
                response = await self.client.aio.models.generate_content(
                    model=self.settings.llm_model, contents=contents, config=config
                )
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
                content = GeneratedAnswer.model_validate_json(response.text)
            except (ValueError, TypeError):
                raise error("invalid_model_output", "Gemini returned invalid answer JSON") from None
            usage = response.usage_metadata
            return Generated(
                content,
                ProviderMetadata(
                    provider="gemini",
                    requested_model=self.settings.llm_model,
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
        try:
            await self.client.aio.aclose()
            self.client.close()
        finally:
            if self._http is not None:
                await self._http.aclose()

    async def check_access(self, timeout):
        """Read account-visible model metadata; this does not establish generation access."""
        try:
            async with asyncio.timeout(timeout):
                model = await self.client.aio.models.get(model=self.settings.llm_model)
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
