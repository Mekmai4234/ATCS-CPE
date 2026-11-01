import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError
from youtube_backend.errors import AppError

from youtube_answers.local import LocalSettings, OllamaModel


def response(**updates):
    return dict(
        {
            "model": "fixture-local:1",
            "done": True,
            "done_reason": "stop",
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "status": "answered",
                        "statements": [{"text": "fixture", "citation_ids": ["fake"]}],
                    }
                ),
            },
            "prompt_eval_count": 30,
            "eval_count": 10,
        },
        **updates,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com:443",
        "http://192.168.1.2:11434",
        "http://localhost:11434",
        "http://127.0.0.1:11434/secret",
        "http://user:secret@127.0.0.1:11434",
    ],
)
def test_only_explicit_loopback_is_allowed(url):
    with pytest.raises(ValidationError):
        LocalSettings(base_url=url, model="fixture:1")


async def test_local_answer_uses_existing_evidence_validation_and_one_request(env):
    sent = []

    async def handle(request):
        data = json.loads(request.content)
        sent.append(data)
        answer = response()
        answer["message"]["content"] = json.dumps(
            {
                "status": "answered",
                "statements": [
                    {
                        "text": "RAG retrieves evidence",
                        "citation_ids": [env.knowledge.chunks[0].chunk_id],
                    }
                ],
            }
        )
        return httpx.Response(200, json=answer)

    model = OllamaModel(
        LocalSettings(model="fixture-local:1", context_tokens=24000),
        transport=httpx.MockTransport(handle),
    )
    env.service.model = model
    try:
        answer = await env.service.answer(env.request, env.sources, [], env.ctx)
        assert answer.provider_metadata.provider == "ollama"
        assert answer.provider_metadata.requested_model == "fixture-local:1"
        assert answer.provider_metadata.returned_model == "fixture-local:1"
        assert answer.citations and answer.coverage.complete
        assert len(sent) == 1 and sent[0]["stream"] is False
        assert sent[0]["format"]["properties"]["statements"]
        assert sent[0]["options"]["num_ctx"] == 24000
    finally:
        await model.close()


@pytest.mark.parametrize(
    "data",
    [
        response(done=False),
        response(done_reason="length"),
        response(model="different"),
        response(message={"role": "assistant", "content": "SECRET INVALID"}),
        response(message={"role": "assistant", "content": "{}", "tool_calls": [{}]}),
        response(eval_count=-1),
    ],
)
async def test_rejects_incomplete_invalid_or_unexpected_output(data):
    model = OllamaModel(
        LocalSettings(model="fixture-local:1"),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
    )
    try:
        with pytest.raises(AppError) as caught:
            await model.generate({}, 1)
        assert caught.value.code == "invalid_model_output"
        assert "SECRET" not in caught.value.message
    finally:
        await model.close()


async def test_fabricated_local_citations_are_not_published(env):
    model = OllamaModel(
        LocalSettings(model="fixture-local:1", context_tokens=24000),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response())),
    )
    env.service.model = model
    try:
        with pytest.raises(AppError) as caught:
            await env.service.answer(env.request, env.sources, [], env.ctx)
        assert caught.value.code == "invalid_citation"
    finally:
        await model.close()


async def test_context_guard_and_no_silent_fallback():
    sent = []

    def handle(request):
        sent.append(request)
        return httpx.Response(503, json={"error": "PRIVATE upstream"})

    model = OllamaModel(
        LocalSettings(model="fixture-local:1"), transport=httpx.MockTransport(handle)
    )
    try:
        with pytest.raises(AppError) as caught:
            await model.generate({"text": "x" * 9000}, 1)
        assert caught.value.code == "context_budget_exceeded" and not sent
        with pytest.raises(AppError) as caught:
            await model.generate({}, 1)
        assert caught.value.code == "local_unavailable" and len(sent) == 1
        assert "PRIVATE" not in caught.value.message
    finally:
        await model.close()


async def test_timeout_and_cancellation_do_not_retry():
    started = asyncio.Event()

    async def handle(request):
        started.set()
        await asyncio.sleep(10)

    model = OllamaModel(
        LocalSettings(model="fixture-local:1"), transport=httpx.MockTransport(handle)
    )
    try:
        with pytest.raises(AppError) as caught:
            await model.generate({}, 0.01)
        assert caught.value.code == "local_timeout"
        started.clear()
        task = asyncio.create_task(model.generate({}, 5))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await model.close()
