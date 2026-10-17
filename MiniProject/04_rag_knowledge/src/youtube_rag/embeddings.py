import asyncio
import hashlib
import math
import re
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types

from .config import RagSettings
from .errors import error


class Embedder(Protocol):
    settings: RagSettings

    async def embed(
        self,
        texts: list[str],
        timeout: float,
        *,
        purpose="document",
        titles: list[str] | None = None,
    ) -> list[list[float]]: ...


def validate_vectors(vectors, expected, dimensions):
    if (
        not isinstance(vectors, (list, tuple))
        or len(vectors) != expected
        or any(
            not isinstance(v, (list, tuple))
            or len(v) != dimensions
            or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                for x in v
            )
            or not any(x != 0 for x in v)
            for v in vectors
        )
    ):
        raise error(
            "invalid_embedding", "Embedding response has invalid shape or values", status=502
        )
    return vectors


def prepare_inputs(texts, *, purpose, titles=None):
    if purpose not in {"document", "query"} or not texts or len(texts) > 64:
        raise error(
            "invalid_embedding_input", "Invalid embedding purpose or batch size", status=422
        )
    if titles is not None and len(titles) != len(texts):
        raise error("invalid_embedding_input", "Titles must match the input batch", status=422)
    prepared = []
    for index, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            raise error("invalid_embedding_input", "Embedding text must be nonempty", status=422)
        if purpose == "query":
            content = f"task: search result | query: {text}"
        else:
            title = titles[index] if titles else "none"
            # Source title is still untrusted data; keep formatting bounded and one line.
            title = " ".join((title or "none").split())[:200]
            content = f"title: {title} | text: {text}"
        if len(content.encode("utf-8")) > 8000:
            raise error(
                "embedding_input_too_long",
                "Prepared input exceeds the local byte budget",
                status=422,
            )
        prepared.append(content)
    return prepared


class GeminiEmbedder:
    """Gemini Developer API only; exact countTokens preflight, independent Content per chunk."""

    def __init__(self, settings: RagSettings, *, client=None):
        if settings.embedding_provider != "gemini":
            raise ValueError("GeminiEmbedder requires the gemini configuration")
        if client is None and not settings.gemini_api_key.get_secret_value():
            raise error("embedding_unavailable", "GEMINI_API_KEY is required", status=503)
        self.settings = settings
        # Pin the async transport so optional aiohttp dependencies cannot change retry/
        # cancellation behavior. The SDK does not own an explicitly supplied HTTPX client.
        self._http_client = (
            httpx.AsyncClient(timeout=settings.rag_operation_timeout_seconds)
            if client is None
            else None
        )
        self.client = client or genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=int(settings.rag_operation_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
                httpx_async_client=self._http_client,
            ),
        )
        self.count_requests = 0
        self.embed_requests = 0
        self.counted_input_tokens = 0

    async def embed(self, texts, timeout, *, purpose="document", titles=None):
        prepared = prepare_inputs(texts, purpose=purpose, titles=titles)
        contents = [types.Content(parts=[types.Part(text=text)]) for text in prepared]
        try:
            # One deadline covers all count requests AND the actual embedding request.
            async with asyncio.timeout(timeout):
                for content in contents:
                    self.count_requests += 1
                    response = await self.client.aio.models.count_tokens(
                        model=self.settings.embedding_model,
                        contents=content,
                    )
                    count = response.total_tokens
                    if type(count) is not int or count <= 0:
                        raise error(
                            "invalid_token_count",
                            "Gemini returned an invalid token count",
                            status=502,
                        )
                    if count > 8192:
                        raise error(
                            "embedding_input_too_long",
                            "Gemini input exceeds 8192 tokens",
                            status=422,
                        )
                    self.counted_input_tokens += count
                self.embed_requests += 1
                response = await self.client.aio.models.embed_content(
                    model=self.settings.embedding_model,
                    contents=contents,
                    config=types.EmbedContentConfig(
                        output_dimensionality=self.settings.embedding_dimensions,
                    ),
                )
            # The SDK's batch endpoint returns one embedding per request, in request order.
            vectors = [item.values for item in response.embeddings or []]
            return validate_vectors(vectors, len(texts), self.settings.embedding_dimensions)
        except (httpx.TimeoutException, TimeoutError):
            raise error(
                "embedding_timeout",
                "Gemini request exceeded its deadline",
                retryable=True,
                status=504,
            ) from None
        except httpx.TransportError:
            raise error(
                "embedding_unavailable",
                "Gemini transport is temporarily unavailable",
                retryable=True,
                status=503,
            ) from None
        except errors.APIError as exc:
            status = exc.code
            transient = status in {408, 429} or (isinstance(status, int) and status >= 500)
            raise error(
                "embedding_provider_error",
                "Gemini rejected the embedding request",
                retryable=transient,
                status=503 if transient else 502,
            ) from None

    async def close(self):
        try:
            await self.client.aio.aclose()
            self.client.close()
        finally:
            if self._http_client is not None:
                await self._http_client.aclose()


class FixtureEmbedder:
    """Deterministic token hashing for offline mechanism checks, not semantic quality."""

    def __init__(self, settings: RagSettings):
        if (
            settings.embedding_provider != "fixture"
            or settings.embedding_model != "fixture-hash-v1"
        ):
            raise ValueError("FixtureEmbedder requires fixture-hash-v1")
        self.settings = settings

    async def embed(self, texts, timeout, *, purpose="document", titles=None):
        prepare_inputs(texts, purpose=purpose, titles=titles)
        result = []
        for text in texts:
            vector = [0.0] * self.settings.embedding_dimensions
            for token in re.findall(r"\w+", text.lower()) or [text]:
                index = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest())
                vector[index % len(vector)] += 1.0
            norm = math.sqrt(sum(v * v for v in vector))
            result.append([v / norm for v in vector])
        await asyncio.sleep(0)
        return result

    async def close(self):
        pass
