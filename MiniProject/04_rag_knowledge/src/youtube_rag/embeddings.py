import asyncio
import hashlib
import math
import re
from typing import Protocol
from uuid import uuid4

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
    requires_execution = True

    """Gemini Developer API only; exact countTokens preflight, independent Content per chunk."""

    def __init__(self, settings: RagSettings, *, client=None, http_client=None):
        if settings.embedding_provider != "gemini":
            raise ValueError("GeminiEmbedder requires the gemini configuration")
        self.settings = settings
        self._api_key = settings.gemini_api_key.get_secret_value()
        # Pin the async transport so optional aiohttp dependencies cannot change retry/
        # cancellation behavior. The SDK does not own an explicitly supplied HTTPX client.
        self._http_client = (
            httpx.AsyncClient(timeout=settings.rag_operation_timeout_seconds)
            if client is None and self._api_key
            else None
        )
        self.client = client or (
            genai.Client(
                api_key=self._api_key,
                vertexai=False,
                http_options=types.HttpOptions(
                    timeout=int(settings.rag_operation_timeout_seconds * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                    httpx_async_client=self._http_client,
                ),
            )
            if self._http_client is not None
            else None
        )
        self._embedding_http = http_client or self._http_client
        self.count_requests = 0
        self.embed_requests = 0
        self.counted_input_tokens = 0

    @property
    def credential_sha256(self):
        return hashlib.sha256(self._api_key.encode()).hexdigest()

    async def embed(self, texts, timeout, *, purpose="document", titles=None, execution=None):
        prepared = prepare_inputs(texts, purpose=purpose, titles=titles)
        call = getattr(execution, "gemini_call", None)
        if not callable(call):
            raise error(
                "gemini_broker_required", "A trusted execution broker is required", status=503
            )
        if self.client is None:
            raise error("embedding_unavailable", "GEMINI_API_KEY is required", status=503)
        from youtube_backend.provider_errors import provider_error
        from youtube_backend.quota import ProviderReply

        async def request(endpoint, content, tokens):
            async def dispatch():
                try:
                    if endpoint == "countTokens":
                        self.count_requests += 1
                        response = await self.client.aio.models.count_tokens(
                            model=self.settings.embedding_model, contents=content
                        )
                        usage = response.total_tokens
                    else:
                        self.embed_requests += 1
                        if self._embedding_http is None:
                            raise error(
                                "embedding_unavailable",
                                "Embedding HTTP transport is missing",
                                status=503,
                            )
                        # google-genai 2.31 expands even one Content into the
                        # synchronous batch endpoint. Use the official single-item
                        # REST endpoint so the actual HTTP endpoint equals the grant.
                        raw = await self._embedding_http.post(
                            "https://generativelanguage.googleapis.com/v1beta/models/"
                            + self.settings.embedding_model
                            + ":embedContent",
                            headers={"x-goog-api-key": self._api_key},
                            json={
                                "model": "models/" + self.settings.embedding_model,
                                "content": content.model_dump(mode="json", exclude_none=True),
                                "outputDimensionality": self.settings.embedding_dimensions,
                            },
                        )
                        if raw.status_code >= 400:
                            raise provider_error(
                                raw.status_code,
                                retry_after=raw.headers.get("retry-after"),
                            )
                        try:
                            response = types.EmbedContentResponse(
                                embeddings=[
                                    types.ContentEmbedding.model_validate(raw.json()["embedding"])
                                ]
                            )
                        except (ValueError, KeyError, TypeError):
                            raise provider_error(502) from None
                        usage = tokens
                    return ProviderReply(response, usage, getattr(response, "model_version", None))
                except errors.APIError as exc:
                    raise provider_error(exc.code) from None
                except (httpx.TimeoutException, TimeoutError):
                    raise provider_error(504, origin="timeout") from None
                except httpx.TransportError:
                    raise provider_error(503, origin="transport") from None

            # One content per HTTP request: never account an SDK batch as one
            # embedContent reservation. No SDK retries or alternate provider.
            reply = await call(
                dispatch,
                model=self.settings.embedding_model,
                endpoint=endpoint,
                input_tokens=tokens,
                call_key=f"04-{endpoint}-{uuid4().hex}",
                input_hash=hashlib.sha256(content.parts[0].text.encode()).hexdigest(),
                role="embedding",
                credential_sha256=hashlib.sha256(self._api_key.encode()).hexdigest(),
            )
            return reply.value

        vectors = []
        try:
            async with asyncio.timeout(timeout):
                for text in prepared:
                    content = types.Content(parts=[types.Part(text=text)])
                    counted = await request("countTokens", content, len(text.encode()) + 128)
                    count = counted.total_tokens
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
                    response = await request("embedContent", content, count)
                    vectors.extend(
                        validate_vectors(
                            [item.values for item in response.embeddings or []],
                            1,
                            self.settings.embedding_dimensions,
                        )
                    )
            return validate_vectors(vectors, len(texts), self.settings.embedding_dimensions)
        except TimeoutError:
            raise error(
                "embedding_timeout",
                "Gemini request exceeded its deadline",
                retryable=True,
                status=504,
            ) from None

    async def close(self):
        if self.client is None:
            return
        try:
            await self.client.aio.aclose()
            self.client.close()
        finally:
            if self._http_client is not None:
                await self._http_client.aclose()


class OllamaEmbedder:
    """Execution-bound local vectors, never admitted through the Gemini budget."""

    requires_execution = True

    def __init__(self, settings):
        if settings.embedding_provider != "ollama":
            raise ValueError("OllamaEmbedder requires an explicit local configuration")
        self.settings = settings

    def policy_identity(self, execution):
        execution.check()
        context = execution.context
        settings = context.settings
        if (
            settings.embedding_provider != "ollama"
            or settings.local_embedding_model != self.settings.embedding_model
            or settings.local_embedding_digest != self.settings.local_embedding_digest
        ):
            raise error("index_configuration_mismatch", "Local embedding identity differs")
        return self.settings.fingerprint

    async def embed(self, texts, timeout, *, purpose="document", titles=None, execution=None):
        if execution is None or not callable(getattr(execution, "local_inference", None)):
            raise error(
                "local_broker_required", "Trusted local execution broker required", status=503
            )
        self.policy_identity(execution)
        prepared = prepare_inputs(texts, purpose=purpose, titles=titles)
        if len(prepared) > self.settings.embedding_batch_size:
            raise error(
                "invalid_embedding_input", "Local batch exceeds configured limit", status=422
            )
        async with asyncio.timeout(timeout):
            response = await execution.local_inference(
                model=self.settings.embedding_model,
                digest=self.settings.local_embedding_digest,
                operation="embed",
                payload={"input": prepared},
                call_key=f"04-local-{uuid4().hex}",
            )
        execution.check()
        return validate_vectors(
            response.get("embeddings"), len(texts), self.settings.embedding_dimensions
        )

    async def close(self):
        pass


def create_embedder(settings):
    return {"fixture": FixtureEmbedder, "gemini": GeminiEmbedder, "ollama": OllamaEmbedder}[
        settings.embedding_provider
    ](settings)


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
