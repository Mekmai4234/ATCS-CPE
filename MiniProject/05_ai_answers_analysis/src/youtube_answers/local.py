"""Explicit experimental Ollama model; not mounted by either production factory.

No downloads, cloud fallback, Gemini broker or automatic repair calls. Use only after
the operator has installed a licensed local model and disabled Ollama cloud support.
"""

import asyncio
import ipaddress
import re
import time
from urllib.parse import urlsplit

import httpx
from pydantic import Field, model_validator
from youtube_backend.schemas import ProviderMetadata, Schema

from .models import Generated, GeneratedAnswer, error
from .prompts import POLICY, json_text
from .timing import provider_call


class LocalSettings(Schema):
    base_url: str = "http://127.0.0.1:11434"
    model: str = Field(min_length=1, max_length=200)
    context_tokens: int = Field(default=8192, ge=2048, le=131072)
    output_tokens: int = Field(default=2048, ge=128, le=32000)
    max_response_bytes: int = Field(default=1000000, ge=1024, le=4000000)

    @model_validator(mode="after")
    def local_only(self):
        url = urlsplit(self.base_url)
        try:
            loopback = ipaddress.ip_address(url.hostname or "").is_loopback
            port = url.port
        except ValueError:
            loopback, port = False, None
        if (
            url.scheme != "http"
            or not loopback
            or port is None
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("Use a literal loopback HTTP host and explicit port")
        if not re.fullmatch(r"[A-Za-z0-9_./:-]+", self.model) or "cloud" in self.model.lower():
            raise ValueError("Configure an installed local model, not a cloud model")
        if self.output_tokens >= self.context_tokens:
            raise ValueError("Output budget must leave room for the prompt")
        return self


class OllamaModel:
    def __init__(self, settings: LocalSettings, *, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        )

    async def generate(
        self,
        payload,
        timeout,
        *,
        schema=GeneratedAnswer,
        policy=POLICY,
        images=(),
        purpose="chat",
        model=None,
        output_limit=None,
    ):
        if images or purpose == "vision" or model not in {None, self.settings.model}:
            raise error("local_unsupported", "This local adapter supports configured text only")
        if self.client.is_closed:
            raise error("local_unavailable", "Local model client is closed", status=503)
        content = json_text(payload)
        # Conservative UTF-8 byte upper bound, including policy/schema/framing. Reserve
        # output too: Ollama otherwise can silently truncate the input at num_ctx.
        prompt_bound = (
            len((content + policy + json_text(schema.model_json_schema())).encode()) + 512
        )
        output = min(output_limit or self.settings.output_tokens, self.settings.output_tokens)
        if prompt_bound + output > self.settings.context_tokens:
            raise error("context_budget_exceeded", "Local prompt and output exceed context budget")
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout):
                provider_call("generate_content")
                async with self.client.stream(
                    "POST",
                    "/api/chat",
                    timeout=timeout,
                    json={
                        "model": self.settings.model,
                        "messages": [
                            {"role": "system", "content": policy},
                            {"role": "user", "content": content},
                        ],
                        "format": schema.model_json_schema(),
                        "stream": False,
                        "options": {
                            "num_ctx": self.settings.context_tokens,
                            "num_predict": output,
                            "temperature": 0,
                        },
                    },
                ) as response:
                    if response.status_code != 200:
                        raise error("local_unavailable", "Local model is not ready", status=503)
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > self.settings.max_response_bytes:
                            raise error("invalid_model_output", "Local response exceeds size limit")
            import json

            data = json.loads(body)
            message = data["message"]
            if (
                data.get("done") is not True
                or data.get("done_reason") != "stop"
                or data.get("model") != self.settings.model
                or message.get("role") != "assistant"
                or message.get("tool_calls")
            ):
                raise ValueError("Incomplete or unexpected local response")
            value = schema.model_validate_json(message["content"])
            usage = {k: data[k] for k in ("prompt_eval_count", "eval_count") if k in data}
            if any(type(v) is not int or v < 0 for v in usage.values()):
                raise ValueError("Invalid local usage")
            return Generated(
                value,
                ProviderMetadata(
                    provider="ollama",
                    requested_model=self.settings.model,
                    returned_model=data["model"],
                    usage=usage,
                    latency_ms=(time.monotonic() - started) * 1000,
                ),
            )
        except (httpx.TimeoutException, TimeoutError):
            raise error("local_timeout", "Local model exceeded its deadline", status=504) from None
        except httpx.TransportError:
            raise error("local_unavailable", "Local model is unreachable", status=503) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise error(
                "invalid_model_output", "Local model returned invalid answer JSON"
            ) from None

    async def close(self):
        await self.client.aclose()
