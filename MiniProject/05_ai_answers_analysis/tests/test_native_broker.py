"""Actual 02 SQL admission + 05 SDK; all Google HTTP responses are local fixtures."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from google import genai
from google.genai import types
from pydantic import SecretStr
from test_integration import integrated as integrated
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.quota import QuotaBroker

from youtube_answers.config import AnswerSettings
from youtube_answers.gemini import GeminiModel
from youtube_answers.quota import ExecutionBroker


@pytest.fixture
async def native(integrated, tmp_path):
    env = integrated
    env.settings.gemini_api_key = SecretStr("fixture-native-key")
    now = datetime.now(UTC)
    policy = {
        "tier": "free",
        "project_ref": "fixture-not-real-google",
        "key_sha256": hashlib.sha256(b"fixture-native-key").hexdigest(),
        "verified_by": "test-only",
        "evidence_ref": "synthetic-attestation",
        "verified_at": (now - timedelta(seconds=10)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "pools": {"shared": {"rpm": 100, "tpm": 1000000, "rpd": 1000, "user_rpm": 100}},
        "models": [
            {
                "model": env.settings.llm_model,
                "bucket": "shared",
                "endpoints": ["countTokens", "generateContent"],
                "roles": ["chat", "agent", "vision"],
                "returned_models": ["fixture-version"],
                "image_capable": True,
            }
        ],
    }
    path = tmp_path / "synthetic-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    env.settings.gemini_free_policy_file = str(path)
    QuotaBroker(env.raw_repo).install_policy()
    env.requests, env.remote_status = [], 200

    def handler(request):
        env.requests.append(request.url.path)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 5})
        if env.remote_status != 200:
            return httpx.Response(
                env.remote_status,
                json={
                    "error": {
                        "code": env.remote_status,
                        "message": "PRIVATE PROVIDER DETAIL",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "status": "answered",
                                            "statements": [
                                                {"text": "Fixture", "citation_ids": ["c1"]}
                                            ],
                                        }
                                    )
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "fixture-version",
                "usageMetadata": {"promptTokenCount": 15},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = genai.Client(
        api_key="fixture-native-key",
        vertexai=False,
        http_options=types.HttpOptions(
            httpx_async_client=http, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    settings = AnswerSettings(_env_file=None, gemini_api_key="fixture-native-key")
    env.bridge = ExecutionBroker(env.raw_repo, settings)
    env.gateway = GeminiModel(settings, client=client, broker=env.bridge)
    try:
        yield env
    finally:
        await env.gateway.close()
        await http.aclose()


def execution(env, kind):
    token = actor_id.set(env.owner["user_id"])
    try:
        body = {"scope": {"video_ids": ["dQw4w9WgXcQ"]}}
        body["question" if kind == "chat" else "goal"] = "Fixture"
        job = env.raw_repo.enqueue(kind, body)
    finally:
        actor_id.reset(token)
    job = env.raw_repo.claim(job["job_id"])
    return ExecutionContext(
        env.raw_repo, job["job_id"], job["lease_token"], job["deadline_at"], env.settings
    )


@pytest.mark.parametrize("kind,role", [("chat", "chat"), ("research", "agent")])
async def test_real_sql_broker_accounts_every_sdk_rpc(native, kind, role):
    env = native
    context = execution(env, kind)
    with env.bridge.bind(context):
        result = await env.gateway.generate({}, 10)
    assert result.metadata.returned_model == "fixture-version" and len(env.requests) == 2
    table = db.v2["reservations"]
    with env.db.read() as c:
        rows = c.execute(sa.select(table).order_by(table.c.created_at)).mappings().all()
    assert [r["endpoint"] for r in rows] == ["countTokens", "generateContent"]
    assert [r["tokens"] for r in rows] == [5, 15]
    assert all(r["state"] == "completed" and r["role"] == role for r in rows)
    assert all(r["job_id"] == context.job_id for r in rows)
    assert env.bridge.execution.get() is None


async def test_unbound_or_unverified_never_reaches_google(native):
    env = native
    with pytest.raises(AppError):
        await env.gateway.generate({}, 5)
    env.settings.gemini_free_policy_file = "does-not-exist.json"
    with env.bridge.bind(execution(env, "chat")), pytest.raises(AppError):
        await env.gateway.generate({}, 5)
    assert not env.requests


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_actual_provider_failure_updates_shared_circuit_without_retry(native, status):
    env = native
    env.remote_status = status
    with env.bridge.bind(execution(env, "chat")), pytest.raises(AppError) as caught:
        await env.gateway.generate({}, 10)
    assert len(env.requests) == 2 and "PRIVATE" not in str(caught.value)
    assert caught.value.failure_origin == "http"
    assert caught.value.provider_status == status
    with env.db.read() as c:
        circuit = c.execute(sa.select(db.v2["circuits"])).mappings().one()
    assert circuit["blocked_until"] > datetime.now(UTC).timestamp()
