"""Actual authenticated API/worker/RAG/broker with a synthetic local HTTP provider."""

import importlib.util
import json
import time
from pathlib import Path

import httpx
import sqlalchemy as sa
from youtube_agent.config import AgentSettings
from youtube_agent.local import LocalModel
from youtube_backend import database as db
from youtube_backend.integrations import ExecutionContext
from youtube_backend.local_inference import LocalInference


async def test_local_quiz_worker_persists_replays_and_isolates_users_without_gemini(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "local_domain", Path(__file__).parents[1] / "test_system.py"
    )
    domain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(domain)
    apps, outbound = [], []

    def handler(request):
        outbound.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "fixture:local", "digest": "a" * 64}]}
            )
        body = json.loads(request.content)
        assert body["stream"] is False
        prompt = json.loads(body["messages"][-1]["content"])
        cid = prompt["untrusted_evidence"][0]["chunk_id"]
        content = {
            "questions": [
                {
                    "question": "RAG ค้นอะไร",
                    "answer": "หลักฐาน",
                    "explanation": "fixture only",
                    "citations": [cid],
                }
            ]
        }
        return httpx.Response(
            200,
            json={
                "model": "fixture:local",
                "done": True,
                "done_reason": "stop",
                "message": {"content": json.dumps(content, ensure_ascii=False)},
            },
        )

    async def local_call(context, **request):
        return await LocalInference(context, transport=httpx.MockTransport(handler)).call(**request)

    monkeypatch.setattr(ExecutionContext, "local_inference", local_call)
    async with domain.system(tmp_path / "state", auth=True, configure_app=apps.append) as (
        client,
        worker,
    ):
        app = apps[0]
        challenge = (await client.get("/api/auth/challenge")).json()
        app.state.auth.verifier = lambda credential, audience: dict(
            sub="local-fixture",
            aud=audience,
            iss="https://accounts.google.com",
            exp=time.time() + 300,
            nonce=challenge["nonce"],
        )
        login = await client.post(
            "/api/auth/google",
            headers={"Origin": "http://localhost:3000"},
            json={"credential": "fixture", "csrf_token": challenge["csrf_token"]},
        )
        assert login.status_code == 200
        client.headers.update(
            {"Origin": "http://localhost:3000", "X-CSRF-Token": login.json()["csrf_token"]}
        )
        imported = await client.post(
            "/api/videos/import", json={"urls": [f"https://youtu.be/{domain.A}"]}
        )
        await worker.run_once(imported.json()["jobs"][0]["job_id"])
        settings = worker.repo.settings
        settings.generation_provider = "ollama"
        settings.local_model = "fixture:local"
        settings.local_model_digest = "a" * 64
        settings.local_context_tokens = 8192
        worker.adapters.agent.settings = AgentSettings.from_backend(settings)
        worker.adapters.agent.model = LocalModel(worker.adapters.agent.settings)
        job = await client.post(
            "/api/learning-artifacts",
            headers={"Idempotency-Key": "local-quiz"},
            json={"type": "quiz", "topic": "RAG", "scope": {"video_ids": [domain.A]}},
        )
        assert job.status_code == 202, job.text
        job_id = job.json()["job_id"]
        await worker.run_once(job_id)
        saved = (await client.get("/api/jobs/" + job_id)).json()
        assert saved["state"] == "completed", saved
        assert outbound.count("/api/chat") == 1
        replay = await client.post(
            "/api/learning-artifacts",
            headers={"Idempotency-Key": "local-quiz"},
            json={"type": "quiz", "topic": "RAG", "scope": {"video_ids": [domain.A]}},
        )
        assert replay.json()["job_id"] == job_id
        assert (await client.get("/api/jobs/" + job_id)).json()["state"] == "completed"
        artifact_id = saved["result"]["artifact_ids"][0]
        artifact = (await client.get("/api/learning-artifacts/" + artifact_id)).json()
        assert artifact["provider_metadata"]["provider"] == "ollama"
        assert outbound.count("/api/chat") == 1
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as other:
            challenge = (await other.get("/api/auth/challenge")).json()
            # Authenticate explicitly as another member.
            app.state.auth.verifier = lambda credential, audience: dict(
                sub="other-fixture",
                aud=audience,
                iss="https://accounts.google.com",
                exp=time.time() + 300,
                nonce=challenge["nonce"],
            )
            response = await other.post(
                "/api/auth/google",
                headers={"Origin": "http://localhost:3000"},
                json={"credential": "fixture", "csrf_token": challenge["csrf_token"]},
            )
            assert response.status_code == 200
            assert (await other.get("/api/jobs/" + job_id)).status_code == 404
            assert (await other.get("/api/learning-artifacts/" + artifact_id)).status_code == 404
        with worker.repo.db.read() as c:
            rows = list(c.execute(sa.select(db.v2["reservations"])).mappings())
        assert len(rows) == 1 and rows[0]["project"] == "local:ollama"
        assert rows[0]["state"] == "completed"
