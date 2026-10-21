"""Identity with real 03/04/05/06 adapters, SQLite and Chroma; external providers doubled."""

import importlib.util
import time
from pathlib import Path

import httpx
import pytest
from youtube_backend.config import Settings


@pytest.mark.asyncio
async def test_authenticated_domain_pipeline_and_other_account_denial(tmp_path):
    assert "auth_enabled" in Settings.model_fields, "AUTH BLOCKED: module 02 contract missing"
    spec = importlib.util.spec_from_file_location(
        "team07_domain_fixtures", Path(__file__).parents[1] / "test_system.py"
    )
    domain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(domain)
    apps = []
    async with domain.system(tmp_path, auth=True, configure_app=apps.append) as (a, worker):
        app = apps[0]

        async def login(client, subject):
            challenge = (await client.get("/api/auth/challenge")).json()
            app.state.auth.verifier = lambda credential, audience: dict(
                sub=subject,
                aud=audience,
                iss="https://accounts.google.com",
                exp=time.time() + 300,
                nonce=challenge["nonce"],
            )
            result = await client.post(
                "/api/auth/google",
                headers={"Origin": "http://localhost:3000"},
                json=dict(credential="fixture07", csrf_token=challenge["csrf_token"]),
            )
            assert result.status_code == 200, result.text
            client.headers["Origin"] = "http://localhost:3000"
            client.headers["X-CSRF-Token"] = result.json()["csrf_token"]

        await login(a, "domain-a")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as b:
            await login(b, "domain-b")
            imported = await a.post(
                "/api/videos/import",
                json={"urls": [f"https://youtu.be/{v}" for v in (domain.A, domain.B)]},
            )
            assert imported.status_code == 202, imported.text
            for item in imported.json()["jobs"]:
                await worker.run_once(item["job_id"])
                result = (await a.get(f"/api/jobs/{item['job_id']}")).json()
                assert result["stage"] == "ready", result
                assert (await b.get(f"/api/jobs/{item['job_id']}")).status_code == 404
            assert (await b.get("/api/videos")).json()["total"] == 0
            assert (await b.get(f"/api/videos/{domain.A}/transcript")).status_code == 404
            scope = dict(video_ids=[domain.A, domain.B])
            chat = await domain.finish(a, worker, "/api/chat", dict(question="RAG", scope=scope))
            assert chat["result"]["citations"]
            assert (await b.get(f"/api/conversations/{chat['conversation_id']}")).status_code == 404
            await domain.finish(
                a, worker, "/api/research", dict(goal="Compare videos", scope=scope)
            )
            artifact = await domain.finish(
                a, worker, "/api/learning-artifacts", dict(type="quiz", scope=scope)
            )
            for identifier in artifact["result"]["artifact_ids"]:
                assert (await b.get(f"/api/learning-artifacts/{identifier}")).status_code == 404
            assert (await a.post("/api/auth/logout")).status_code == 200
            assert (await a.get("/api/videos")).status_code == 401
