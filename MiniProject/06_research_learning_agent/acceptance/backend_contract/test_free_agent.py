"""Real 02 durable quota admission; SDK HTTP responses are fixtures only."""

import json

import httpx
import pytest
import sqlalchemy as sa
from google import genai
from google.genai import types
from test_free_tier import budget as shared_budget
from test_identity import identity as backend_identity
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext

from youtube_agent.config import AgentSettings
from youtube_agent.gemini import GeminiModel

identity = backend_identity
budget = shared_budget


@pytest.fixture
async def admitted_model(budget):
    env = budget
    env.policy["pools"]["shared"].update(rpm=100, user_rpm=100, rpd=1000, tpm=500000)
    env.policy["models"][0]["returned_models"] = ["fixture-version"]
    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    env.broker.install_policy()
    token = actor_id.set(env.user["user_id"])
    try:
        queued = env.repo.enqueue(
            "research", {"goal": "RAG", "scope": {"video_ids": ["dQw4w9WgXcQ"]}}
        )
    finally:
        actor_id.reset(token)
    job = env.repo.claim(queued["job_id"])
    env.agent_context = ExecutionContext(
        env.repo, job["job_id"], job["lease_token"], job["deadline_at"], env.settings
    )
    env.requests, env.remote_status = [], 200

    def handler(request):
        env.requests.append(request.url.path)
        if env.remote_status != 200:
            return httpx.Response(
                env.remote_status,
                json={"error": {"code": env.remote_status, "message": "PRIVATE PROVIDER BODY"}},
            )
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 10})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "finish_research",
                                        "args": {"content": "Fixture", "citation_ids": []},
                                    }
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "fixture-version",
                "usageMetadata": {"promptTokenCount": 10},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = genai.Client(
        api_key="fixture-free-project-key",
        vertexai=False,
        http_options=types.HttpOptions(
            httpx_async_client=http, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    env.agent_model = GeminiModel(
        AgentSettings(_env_file=None, gemini_api_key=env.settings.gemini_api_key), client=client
    )
    try:
        yield env
    finally:
        await env.agent_model.close()
        await http.aclose()


async def test_real_project_gate_accounts_for_count_and_generation(admitted_model):
    env = admitted_model
    result = await env.agent_model.decide(
        [{"role": "user", "data": {"goal": "RAG"}}], 10, context=env.agent_context
    )
    assert result.metadata.returned_model == "fixture-version" and len(env.requests) == 2
    with env.db.read() as c:
        rows = list(c.execute(sa.select(db.v2["reservations"])).mappings())
        assert len(rows) == 2
        assert {r["role"] for r in rows} == {"agent"}


async def test_unverified_project_cannot_even_send_count_tokens(admitted_model):
    env = admitted_model
    env.settings.gemini_free_policy_file = "missing-fixture-policy.json"
    with pytest.raises(AppError) as exc:
        await env.agent_model.decide([{"role": "user", "data": {}}], 10, context=env.agent_context)
    assert exc.value.code == "free_tier_unverified" and not env.requests


async def test_agent_cannot_use_a_different_project_credential(admitted_model):
    from pydantic import SecretStr

    env = admitted_model
    env.agent_model.settings.gemini_api_key = SecretStr("unattested-other-project")
    with pytest.raises(AppError) as exc:
        await env.agent_model.decide([{"role": "user", "data": {}}], 10, context=env.agent_context)
    assert exc.value.code == "free_tier_unverified" and not env.requests


@pytest.mark.parametrize(
    "status,code", [(429, "provider_rate_limited"), (503, "provider_unavailable")]
)
async def test_provider_errors_reach_shared_broker_without_retry(admitted_model, status, code):
    env = admitted_model
    env.remote_status = status
    with pytest.raises(AppError) as exc:
        await env.agent_model.decide([{"role": "user", "data": {}}], 10, context=env.agent_context)
    assert exc.value.code == code and len(env.requests) == 1
    assert "PRIVATE" not in str(exc.value)
