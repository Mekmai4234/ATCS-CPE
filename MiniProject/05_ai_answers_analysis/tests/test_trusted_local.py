import json

import httpx
import pytest
import sqlalchemy as sa
from test_integration import integrated as integrated
from youtube_backend import database as db
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.local_inference import LocalInference

from youtube_answers.config import AnswerSettings
from youtube_answers.configuration import resolved_service
from youtube_answers.trusted_local import TrustedLocalModel


@pytest.mark.parametrize(
    "kind", ["chat", "summary", "compare", "retry", "vision", "mismatch", "fabricated"]
)
async def test_authenticated_local_worker_uses_actual_broker_and_preserves_citations(
    integrated, monkeypatch, kind
):
    env = integrated
    env.settings.generation_provider = "ollama"
    env.settings.local_model = "fixture-local:1"
    env.settings.local_model_digest = "a" * 64
    env.settings.local_context_tokens = 24000
    env.answers.answers.settings = resolved_service(env.settings, AnswerSettings)
    env.answers.answers.model = TrustedLocalModel(env.answers.answers.settings)
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "fixture-local:1",
                            "digest": ("b" if kind == "mismatch" else "a") * 64,
                        }
                    ]
                },
            )
        payload = json.loads(json.loads(req.content)["messages"][1]["content"])
        refs = list(
            dict.fromkeys(
                cid for node in payload["untrusted_evidence"] for cid in node["citation_ids"]
            )
        )
        if kind == "fabricated":
            refs = ["invented"]
        return httpx.Response(
            200,
            json={
                "model": "fixture-local:1",
                "done": True,
                "done_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": "answered",
                            "statements": [{"text": "[FIXTURE] supported", "citation_ids": refs}],
                        }
                    ),
                },
            },
        )

    async def local_call(context, **kwargs):
        return await LocalInference(context, transport=httpx.MockTransport(handler)).call(**kwargs)

    monkeypatch.setattr(ExecutionContext, "local_inference", local_call)
    ids = (
        [s.video_id for s in env.sources]
        if hasattr(env, "sources")
        else ["dQw4w9WgXcQ", "jNQXAC9IVRw"]
    )
    chat = kind not in {"summary", "compare"}
    route = "/api/chat" if chat else "/api/analysis"
    body = (
        {"question": "RAG", "scope": {"video_ids": ids[:1]}}
        if chat
        else {"type": kind, "scope": {"video_ids": ids if kind == "compare" else ids[:1]}}
    )
    if kind == "vision":
        body["question"] = "ในภาพที่เวลา 01:00 มีอะไร"
    if kind == "retry":
        original = env.answers.answers.knowledge.evidence
        attempts = []

        async def fail_once(*args):
            attempts.append(True)
            if len(attempts) == 1:
                raise AppError(
                    "index_unavailable", "Fixture temporary validation outage", 503, True
                )
            return await original(*args)

        monkeypatch.setattr(env.answers.answers.knowledge, "evidence", fail_once)
    accepted = await env.client.post(route, json=body)
    assert accepted.status_code in {200, 202}, accepted.text
    job_id = accepted.json()["job_id"]
    await env.worker.run_once(job_id)
    if kind == "retry":
        assert env.repo.get_job(job_id)["state"] == "queued"
        await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    if kind in {"vision", "mismatch", "fabricated"}:
        assert job["result"] is None
        assert (
            job["error_code"]
            == {
                "vision": "local_unsupported",
                "mismatch": "local_model_changed",
                "fabricated": "invalid_citation",
            }[kind]
        )
        if kind in {"vision", "mismatch"}:
            assert "/api/chat" not in seen
        return
    assert job["state"] == "completed", job
    assert job["result"]["provider_metadata"]["provider"] == (
        "ollama-cache" if kind == "retry" else "ollama"
    )
    if kind == "retry":
        assert seen.count("/api/chat") == 1
    assert job["result"]["citations"]
    with env.db.read() as c:
        rows = list(c.execute(sa.select(db.v2["reservations"])).mappings())
    assert rows and all(r["project"] == "local:ollama" and r["state"] == "completed" for r in rows)
    calls = seen.count("/api/chat")
    for _ in range(2):
        response = await env.client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
    assert seen.count("/api/chat") == calls


async def test_production_team_factory_mounts_local_without_constructing_gemini(
    integrated, monkeypatch
):
    from youtube_answers import team

    settings = integrated.settings.model_copy(
        update={
            "backend_integration_profile": "live",
            "adapter_factory": "youtube_answers.team:create_adapters",
            "generation_provider": "ollama",
            "local_model": "fixture-local:1",
            "local_model_digest": "a" * 64,
        }
    )

    def forbidden(*args, **kwargs):
        pytest.fail("No Gemini generation client may be constructed for local generation")

    monkeypatch.setattr(team, "GeminiModel", forbidden)
    adapters = await team.create_adapters(settings=settings, repository=integrated.repo)
    try:
        assert isinstance(adapters.answers.answers.model, TrustedLocalModel)
        assert all(
            adapters.provider_operations[k] == "local"
            for k in ("answer", "analyze", "companion", "research", "artifact", "grade_quiz")
        )
        assert adapters.agent.media_answerer is None
    finally:
        await adapters.close()
