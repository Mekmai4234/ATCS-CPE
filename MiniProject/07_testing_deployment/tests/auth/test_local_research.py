"""Multi-page actual authenticated API/worker/RAG, synthetic local HTTP generation."""

import importlib.util
import json
import time
from pathlib import Path

import httpx
from youtube_agent.config import AgentSettings
from youtube_agent.local import LocalModel
from youtube_backend.integrations import ExecutionContext
from youtube_backend.local_inference import LocalInference


async def test_local_research_synthesizes_32_real_rag_chunks_with_default_budgets(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "multipage_domain", Path(__file__).parents[1] / "test_system.py"
    )
    domain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(domain)
    apps, generations = [], []

    async def captions(self, video_id, languages, timeout):
        return dict(
            video_id=video_id,
            language="en",
            is_generated=False,
            segments=[
                dict(text=f"Fact {i}: RAG uses evidence.", start=i * 3.0, duration=3.0)
                for i in range(32)
            ],
        )

    monkeypatch.setattr(domain.CaptionProvider, "fetch", captions)

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "fixture:local", "digest": "a" * 64}]}
            )
        prompt = json.loads(json.loads(request.content)["messages"][-1]["content"])
        generations.append(prompt)
        content = {
            "content": "[FIXTURE] RAG uses evidence from all supplied facts.",
            "citation_ids": [prompt["untrusted_evidence"][0]["chunk_id"]],
        }
        return httpx.Response(
            200,
            json={
                "model": "fixture:local",
                "done": True,
                "done_reason": "stop",
                "message": {"content": json.dumps(content)},
                "prompt_eval_count": 100,
                "eval_count": 20,
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
            sub="multipage-fixture",
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
        config = worker.adapters.answers.rag.settings
        config.chunk_target_tokens, config.chunk_overlap_tokens = 32, 0
        imported = await client.post(
            "/api/videos/import", json={"urls": [f"https://youtu.be/{domain.A}"]}
        )
        await worker.run_once(imported.json()["jobs"][0]["job_id"])
        settings = worker.repo.settings
        settings.generation_provider, settings.local_model = "ollama", "fixture:local"
        settings.local_model_digest, settings.local_context_tokens = "a" * 64, 32768
        agent = worker.adapters.agent
        agent.settings = AgentSettings.from_backend(settings)
        assert agent.settings.agent_max_model_calls == 4 and agent.settings.agent_max_steps == 8
        agent.model = LocalModel(agent.settings)
        job = await client.post(
            "/api/research",
            json={"goal": "Summarize RAG facts", "scope": {"video_ids": [domain.A]}},
            headers={"Idempotency-Key": "multipage-local"},
        )
        assert job.status_code == 202, job.text
        job_id = job.json()["run_id"]
        await worker.run_once(job_id)
        saved = (await client.get("/api/jobs/" + job_id)).json()
        assert saved["state"] == "completed", saved
        result = saved["result"]
        assert result["coverage"]["expected_chunks"] == 32
        assert result["coverage"]["processed_chunks"] == 32
        assert result["coverage"]["complete"] is True
        assert result["provider_metadata"]["provider"] == "ollama"
        assert len(generations) == 1 and len(generations[0]["untrusted_evidence"]) == 32
        assert (await client.get("/api/jobs/" + job_id)).json()["result"] == result
        assert len(generations) == 1
