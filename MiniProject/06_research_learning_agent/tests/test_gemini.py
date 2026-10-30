import asyncio
import json
from functools import partial

import httpx
import pytest
from conftest import Context, evidence
from google import genai
from google.genai import types
from youtube_backend.errors import AppError
from youtube_backend.schemas import QuizContent

from youtube_agent.config import AgentSettings
from youtube_agent.gemini import GeminiModel


class MockBrokerContext(Context):
    """SDK wire fixture only; actual 02 admission is tested in backend_contract."""

    async def gemini_call(self, callback, **request):
        self.check()
        return await callback()


def response(parts=None, *, finish="STOP"):
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": parts
                    or [
                        {
                            "functionCall": {
                                "name": "read_video_chunks",
                                "args": {},
                                "id": "call-1",
                            },
                            "thoughtSignature": "c2lnbmF0dXJl",
                        }
                    ],
                },
                "finishReason": finish,
            }
        ],
        "modelVersion": "fixture-returned-model",
        "usageMetadata": {"promptTokenCount": 17, "candidatesTokenCount": 8},
    }


@pytest.fixture
async def make_model():
    opened = []

    def create(handler, **kwargs):
        transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = genai.Client(
            api_key="test-only-secret",
            vertexai=False,
            http_options=types.HttpOptions(
                httpx_async_client=transport, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        model = GeminiModel(AgentSettings(_env_file=None, **kwargs), client=client)
        context = MockBrokerContext()
        context.settings = model.settings
        model.decide = partial(model.decide, context=context)
        model.generate = partial(model.generate, context=context)
        opened.append((model, transport))
        return model

    yield create
    for model, transport in opened:
        await model.close()
        await transport.aclose()


async def test_native_calls_signatures_ids_and_policy_survive_roundtrip(make_model):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 100})
        return httpx.Response(200, json=response())

    model = make_model(handler)
    history = [{"role": "user", "data": {"goal": "Learn RAG"}}]
    first = await model.decide(history, 5)
    history += [
        {"role": "model", "native": first.native},
        {
            "role": "tool",
            "name": first.name,
            "call_id": "call-1",
            "result": {"evidence": [evidence().model_dump()]},
        },
    ]
    second = await model.decide(history, 5)
    assert first.name == "read_video_chunks"
    assert second.metadata.returned_model == "fixture-returned-model"
    assert second.metadata.usage["prompt_token_count"] == 17
    assert len(requests) == 4
    assert requests[0][0].endswith(":countTokens")
    first_body = requests[1][1]
    assert "ONLY the authorized" in json.dumps(first_body["systemInstruction"])
    assert first_body["generationConfig"]["thinkingConfig"] == {"thinking_level": "LOW"}
    assert first_body["generationConfig"]["maxOutputTokens"] == 8192
    assert len(first_body["tools"][0]["functionDeclarations"]) == 5
    assert first_body["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    last = requests[-1][1]
    assert last["contents"][1]["parts"][0]["thoughtSignature"] == "c2lnbmF0dXJl"
    assert last["contents"][2]["parts"][0]["functionResponse"]["id"] == "call-1"
    assert "Ignore policy" not in last["systemInstruction"]["parts"][0]["text"]
    # Developer API preflight counts native conversation; config gets a separate byte allowance.
    assert requests[0][1]["contents"][0]["parts"][0]["text"] == '{"goal":"Learn RAG"}'


async def test_structured_artifact_uses_schema_and_known_chunk_ids(make_model):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 10})
        return httpx.Response(
            200,
            json=response(
                [
                    {
                        "text": json.dumps(
                            {
                                "questions": [
                                    {
                                        "question": "What does RAG retrieve?",
                                        "answer": "Evidence",
                                        "explanation": "It retrieves evidence",
                                        "citations": ["chunk-1"],
                                    }
                                ]
                            }
                        )
                    }
                ]
            ),
        )

    model = make_model(handler)
    result = await model.generate({"type": "quiz"}, [evidence()], QuizContent, 5)
    assert result.content.questions[0].citations == ["chunk-1"]
    assert requests[-1]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize(
    "status,retryable",
    [
        (400, False),
        (401, False),
        (403, False),
        (429, True),
        (500, False),
        (503, True),
    ],
)
async def test_errors_redacted_and_sdk_does_not_retry(make_model, status, retryable):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, json={"error": {"code": status, "message": "test-only-secret LEAK"}}
        )

    model = make_model(handler)
    with pytest.raises(AppError) as caught:
        await model.decide([{"role": "user", "data": {}}], 5)
    assert caught.value.retryable is retryable
    assert "LEAK" not in str(caught.value) and "secret" not in str(caught.value)
    assert len(requests) == 1
    if status in {429, 503}:
        assert (
            caught.value.code == {429: "provider_rate_limited", 503: "provider_unavailable"}[status]
        )


async def test_no_shared_context_refuses_even_token_count(make_model):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response())

    model = make_model(handler)
    with pytest.raises(AppError) as exc:
        await GeminiModel.decide(model, [{"role": "user", "data": {}}], 5)
    assert exc.value.code == "free_tier_unverified" and not calls


@pytest.mark.parametrize("count", [0, None, 24001])
async def test_bad_token_count_prevents_generation(make_model, count):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"totalTokens": count})

    model = make_model(handler, max_context_tokens=24000)
    with pytest.raises(AppError):
        await model.decide([{"role": "user", "data": {}}], 5)
    assert len(requests) == 1 and requests[0].url.path.endswith(":countTokens")


@pytest.mark.parametrize(
    "parts,finish",
    [
        ([{"text": "Call read_video_chunks"}], "STOP"),
        ([{"functionCall": {"name": "send_email", "args": {}}}], "STOP"),
        ([{"functionCall": {"name": "read_video_chunks", "args": {}}}] * 2, "STOP"),
        ([{"functionCall": {"name": "read_video_chunks", "args": {}}}], "MAX_TOKENS"),
    ],
)
async def test_invalid_function_output_is_rejected(make_model, parts, finish):
    def handler(request):
        data = (
            {"totalTokens": 1}
            if request.url.path.endswith(":countTokens")
            else response(parts, finish=finish)
        )
        return httpx.Response(200, json=data)

    model = make_model(handler, max_context_tokens=24000)
    with pytest.raises(AppError):
        await model.decide([{"role": "user", "data": {}}], 5)


async def test_invalid_json_and_no_candidates_rejected(make_model):
    answers = [response([{"text": "not JSON"}]), {"candidates": []}]

    def handler(request):
        data = {"totalTokens": 1} if request.url.path.endswith(":countTokens") else answers.pop(0)
        return httpx.Response(200, json=data)

    model = make_model(handler)
    for _ in range(2):
        with pytest.raises(AppError):
            await model.generate({"type": "quiz"}, [evidence()], QuizContent, 5)


async def test_transport_failure_is_safe(make_model):
    def handler(request):
        raise httpx.ConnectError("test-only-secret", request=request)

    model = make_model(handler)
    with pytest.raises(AppError) as caught:
        await model.decide([{"role": "user", "data": {}}], 5)
    assert caught.value.code == "provider_unavailable"
    assert "secret" not in str(caught.value)


async def test_preflight_and_generation_share_timeout(make_model):
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"totalTokens": 1})

    model = make_model(handler)
    with pytest.raises(AppError) as caught:
        await model.decide([{"role": "user", "data": {}}], 0.01)
    assert caught.value.code == "generation_timeout"
