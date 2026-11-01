"""Actual 06 adapter mounted behind 02; synthetic captions, embeddings and local HTTP."""

import importlib.util
import json
import time
from pathlib import Path

import httpx
from youtube_agent.config import AgentSettings
from youtube_agent.integration import AgentAdapters
from youtube_agent.local import LocalModel
from youtube_backend.integrations import ExecutionContext
from youtube_backend.local_inference import LocalInference
from youtube_rag.embeddings import FixtureEmbedder


async def test_owned_factory_fresh_quiz_grade_history_and_replay(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "owned_learning_domain", Path(__file__).parents[1] / "test_system.py"
    )
    domain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(domain)
    apps, calls = [], []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "fixture:local", "digest": "a" * 64}]}
            )
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        calls.append(payload)
        if "questions" in payload:
            assert payload["questions"][0]["answer"] == "หลักฐาน"
            content = {
                "marks": [
                    {"correct": answer.strip() == "ข้อมูลหลักฐาน", "feedback": "fixture mark"}
                    for answer in payload["answers"]
                ]
            }
        else:
            cid = payload["untrusted_evidence"][0]["chunk_id"]
            content = {
                "questions": [
                    {
                        "question": "RAG ใช้สิ่งใด",
                        "answer": "หลักฐาน",
                        "explanation": "fixture explanation",
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

    async def invoke(context, **request):
        return await LocalInference(context, transport=httpx.MockTransport(handler)).call(**request)

    monkeypatch.setattr(ExecutionContext, "local_inference", invoke)
    async with domain.system(tmp_path / "state", auth=True, configure_app=apps.append) as (
        client,
        worker,
    ):
        app = apps[0]
        challenge = (await client.get("/api/auth/challenge")).json()
        app.state.auth.verifier = lambda credential, audience: dict(
            sub="owned-learning",
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
        settings.generation_provider, settings.local_model = "ollama", "fixture:local"
        settings.local_model_digest, settings.local_context_tokens = "a" * 64, 8192
        rag_config = worker.adapters.answers.rag.settings
        config = AgentSettings.from_backend(settings)
        owned = AgentAdapters(
            settings=settings,
            repository=worker.repo,
            agent_settings=config,
            model=LocalModel(config),
            rag_settings=rag_config,
            embedder=FixtureEmbedder(rag_config),
        )
        worker.adapters = owned
        app.state.adapters.adapter = owned
        try:
            created = await client.post(
                "/api/learning-artifacts", json={"type": "quiz", "scope": {"video_ids": [domain.A]}}
            )
            job_id = created.json()["job_id"]
            await worker.run_once(job_id)
            saved = (await client.get("/api/jobs/" + job_id)).json()
            assert saved["state"] == "completed", saved
            assert len(calls) == 1
            assert saved["execution"]["provider"] == "ollama"
            artifact = saved["result"]["artifact_ids"][0]
            assert (await client.get("/api/learning-artifacts/" + artifact)).json()[
                "provider_metadata"
            ]["provider"] == "ollama"
            fresh = await client.post(
                f"/api/jobs/{job_id}/regenerate", headers={"Idempotency-Key": "fresh"}
            )
            assert fresh.status_code == 202, fresh.text
            fresh_id = fresh.json()["job_id"]
            await worker.run_once(fresh_id)
            assert (await client.get("/api/jobs/" + fresh_id)).json()["state"] == "completed"
            assert len(calls) == 2
            assert (
                await client.post(
                    f"/api/jobs/{job_id}/regenerate", headers={"Idempotency-Key": "fresh"}
                )
            ).json()["job_id"] == fresh_id
            submission = await client.post(
                f"/api/learning-artifacts/{artifact}/submit",
                json={"answers": ["ข้อมูลหลักฐาน"]},
                headers={"Idempotency-Key": "grade"},
            )
            assert submission.status_code == 202, submission.text
            grade_id = submission.json()["job_id"]
            await worker.run_once(grade_id)
            score = (await client.get("/api/jobs/" + grade_id)).json()
            assert score["state"] == "completed", score
            assert score["result"]["correct"] == 1 and score["result"]["total"] == 1
            assert len(calls) == 3
            assert (
                await client.post(
                    f"/api/learning-artifacts/{artifact}/submit",
                    json={"answers": ["ข้อมูลหลักฐาน"]},
                    headers={"Idempotency-Key": "grade"},
                )
            ).json()["job_id"] == grade_id
            assert (await client.get("/api/jobs/" + grade_id)).json()["result"] == score["result"]
            assert len(calls) == 3
            assert (
                await client.post(
                    f"/api/learning-artifacts/{artifact}/submit", json={"answers": []}
                )
            ).status_code == 422
        finally:
            await owned.close()
