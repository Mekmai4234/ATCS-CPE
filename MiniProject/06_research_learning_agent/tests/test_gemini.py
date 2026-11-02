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
    assert "write in Thai" in first_body["systemInstruction"]["parts"][0]["text"]
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
    assert "maxItems" not in json.dumps(requests[-1]["generationConfig"]["responseJsonSchema"])
    assert QuizContent.model_json_schema()["properties"]["questions"]["maxItems"] == 100


@pytest.mark.parametrize(
    "status,retryable",
    [
        (400, False),
        (401, False),
        (403, False),
        (429, True),
        (500, True),
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
    assert caught.value.failure_origin == "http"
    assert caught.value.provider_status == status
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
    assert caught.value.failure_origin == "transport"
    assert caught.value.provider_status is None
    assert "secret" not in str(caught.value)


async def test_preflight_and_generation_share_timeout(make_model):
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"totalTokens": 1})

    model = make_model(handler)
    with pytest.raises(AppError) as caught:
        await model.decide([{"role": "user", "data": {}}], 0.01)
    assert caught.value.code == "generation_timeout"


async def test_grading_uses_structured_marks_and_same_broker_gate(make_model):
    def handler(request):
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 100})
        body = json.loads(request.content)
        assert "student answers" in body["systemInstruction"]["parts"][0]["text"]
        return httpx.Response(
            200,
            json=response(
                [
                    {
                        "text": json.dumps(
                            {"marks": [{"correct": True, "feedback": "ตอบได้ตรงความหมาย"}]}
                        )
                    }
                ]
            ),
        )

    model = make_model(handler)
    context = MockBrokerContext()
    context.settings = model.settings
    result = await model.grade_quiz(
        {
            "questions": [{"question": "RAG?", "answer": "retrieval"}],
            "answers": ["retrieve evidence"],
        },
        30,
        context=context,
    )
    assert result["marks"][0]["correct"] is True


class LimitedBrokerContext(MockBrokerContext):
    """Broker double: rate-limit chosen model buckets, refuse models absent from policy."""

    def __init__(self, limited=(), unapproved=()):
        super().__init__()
        self.limited, self.unapproved, self.requests = set(limited), set(unapproved), []

    async def gemini_call(self, callback, **request):
        self.requests.append((request["model"], request["endpoint"]))
        if request["model"] in self.unapproved:
            raise AppError("free_model_unverified", "Model is not explicitly approved", 503)
        if request["model"] in self.limited:
            raise AppError("quota_wait", "Local project budget is unavailable", 429, True)
        return await super().gemini_call(callback, **request)


def fallback_agent(handler, context, fallbacks="gemini-3.8-flash"):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = genai.Client(
        api_key="test-only-secret",
        vertexai=False,
        http_options=types.HttpOptions(
            httpx_async_client=http, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    settings = AgentSettings(_env_file=None, llm_fallback_models=fallbacks)
    context.settings = settings
    return GeminiModel(settings, client=client), http


def wire(paths, bodies=None, *, outage=None):
    def handler(request):
        paths.append(request.url.path)
        if bodies is not None:
            bodies.append(json.loads(request.content))
        if outage and outage in request.url.path and request.url.path.endswith(":generateContent"):
            return httpx.Response(503, json={"error": {"code": 503, "message": "busy"}})
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 12})
        return httpx.Response(200, json=response())

    return handler


def test_agent_model_chain_keeps_primary_first_and_drops_duplicates():
    settings = AgentSettings(
        _env_file=None, llm_model="gemini-a", llm_fallback_models=" gemini-b,gemini-a,,gemini-c"
    )
    assert settings.model_chain() == ["gemini-a", "gemini-b", "gemini-c"]


async def test_first_decision_falls_back_and_later_turns_stay_on_that_model():
    paths, context = [], LimitedBrokerContext(limited={"gemini-3.5-flash"})
    model, http = fallback_agent(wire(paths), context)
    try:
        reply = await model.decide([{"role": "user", "data": {}}], 5, context=context)
        assert reply.metadata.requested_model == "gemini-3.8-flash"
        assert reply.metadata.fallback_from == "gemini-3.5-flash"
        history = [
            {"role": "user", "data": {}},
            {
                "role": "model",
                "native": reply.native,
                "name": reply.name,
                "arguments": {},
                "model": reply.metadata.requested_model,
            },
            {"role": "tool", "name": reply.name, "call_id": "call-1", "result": {"ok": True}},
        ]
        context.limited.clear()
        context.requests.clear()
        second = await model.decide(history, 5, context=context)
    finally:
        await model.close()
        await http.aclose()
    # Primary is available again, but the signed turn pins the run to the fallback.
    assert second.metadata.requested_model == "gemini-3.8-flash"
    assert second.metadata.fallback_from == "gemini-3.5-flash"
    assert {name for name, _ in context.requests} == {"gemini-3.8-flash"}


async def test_legacy_turn_without_model_stays_on_primary_and_never_falls_back():
    paths, context = [], LimitedBrokerContext(limited={"gemini-3.5-flash"})
    model, http = fallback_agent(wire(paths), context)
    history = [
        {"role": "user", "data": {}},
        {"role": "model", "native": types.Content(role="model", parts=[types.Part(text="x")])},
        {"role": "user", "data": {}},
    ]
    try:
        with pytest.raises(AppError) as caught:
            await model.decide(history, 5, context=context)
    finally:
        await model.close()
        await http.aclose()
    assert caught.value.code == "quota_wait"
    assert {name for name, _ in context.requests} == {"gemini-3.5-flash"}


async def test_artifact_generation_falls_back_on_primary_outage():
    paths, context = [], LimitedBrokerContext()
    output = {
        "questions": [
            {
                "question": "What does RAG retrieve?",
                "answer": "Evidence",
                "explanation": "It retrieves evidence",
                "citations": ["chunk-1"],
            }
        ]
    }

    def handler(request):
        paths.append(request.url.path)
        if "gemini-3.5-flash:" in request.url.path and request.url.path.endswith(
            ":generateContent"
        ):
            return httpx.Response(503, json={"error": {"code": 503, "message": "busy"}})
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 12})
        return httpx.Response(200, json=response([{"text": json.dumps(output)}]))

    model, http = fallback_agent(handler, context)
    try:
        result = await model.generate(
            {"type": "quiz"}, [evidence()], QuizContent, 5, context=context
        )
    finally:
        await model.close()
        await http.aclose()
    assert result.metadata.requested_model == "gemini-3.8-flash"
    assert result.metadata.fallback_from == "gemini-3.5-flash"
    assert sum(p.endswith(":generateContent") for p in paths) == 2


async def test_unapproved_fallback_is_skipped_and_primary_limit_reported():
    paths, context = (
        [],
        LimitedBrokerContext(limited={"gemini-3.5-flash"}, unapproved={"gemini-3.8-flash"}),
    )
    model, http = fallback_agent(wire(paths), context)
    try:
        with pytest.raises(AppError) as caught:
            await model.decide([{"role": "user", "data": {}}], 5, context=context)
    finally:
        await model.close()
        await http.aclose()
    assert caught.value.code == "quota_wait" and paths == []


async def test_thinking_level_is_dropped_for_non_gemini3_flash_fallback():
    paths, bodies = [], []
    context = LimitedBrokerContext(limited={"gemini-3.5-flash"})
    model, http = fallback_agent(wire(paths, bodies), context, fallbacks="gemini-2.5-flash-lite")
    try:
        await model.decide([{"role": "user", "data": {}}], 5, context=context)
    finally:
        await model.close()
        await http.aclose()
    generate = [b for p, b in zip(paths, bodies, strict=True) if p.endswith(":generateContent")]
    assert generate and "thinkingConfig" not in generate[0].get("generationConfig", {})


def test_usage_reports_the_model_that_answered_after_fallback():
    from youtube_backend.schemas import ProviderMetadata

    from youtube_agent.models import Usage

    usage = Usage(requested_model="gemini-3.5-flash")
    usage.add(
        ProviderMetadata(
            provider="gemini",
            requested_model="gemini-3.8-flash",
            latency_ms=1,
            fallback_from="gemini-3.5-flash",
        )
    )
    result = usage.result()
    assert result.requested_model == "gemini-3.8-flash"
    assert result.fallback_from == "gemini-3.5-flash"


def test_finish_schema_requires_citations_from_observed_evidence():
    """Regression: flash-lite finished with no citation_ids and the run became partial."""
    from youtube_agent.gemini import finish_schema, provider_schema
    from youtube_agent.models import FinishArgs

    history = [
        {"role": "user", "data": {}},
        {
            "role": "tool",
            "name": "search_evidence",
            "result": {
                "evidence": [{"chunk_id": "doc:2", "text": "b"}, {"chunk_id": "doc:1", "text": "a"}]
            },
        },
        {"role": "tool", "name": "read_video_chunks", "result": {"error": "x"}},
    ]
    schema = finish_schema(provider_schema(FinishArgs), history)
    assert schema["properties"]["citation_ids"]["items"]["enum"] == ["doc:1", "doc:2"]
    assert schema["properties"]["citation_ids"]["minItems"] == 1
    assert "citation_ids" in schema["required"]
    untouched = finish_schema(provider_schema(FinishArgs), [{"role": "user", "data": {}}])
    assert "enum" not in json.dumps(untouched)


async def test_finish_declaration_on_the_wire_lists_observed_ids(make_model):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 10})
        return httpx.Response(200, json=response())

    model = make_model(handler)
    history = [
        {"role": "user", "data": {}},
        {
            "role": "tool",
            "name": "search_evidence",
            "call_id": "c",
            "result": {"evidence": [{"chunk_id": "doc:7", "text": "t"}]},
        },
        {"role": "user", "data": {}},
    ]
    await model.decide(history, 5)
    tools = bodies[-1]["tools"][0]["functionDeclarations"]
    finish = next(t for t in tools if t["name"] == "finish_research")
    assert finish["parameters_json_schema"]["properties"]["citation_ids"]["items"]["enum"] == [
        "doc:7"
    ]
