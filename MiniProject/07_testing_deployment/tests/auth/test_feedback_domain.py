"""03/04/05/02 publication, feedback and cold restore with local provider doubles."""

import importlib.util
import time
from pathlib import Path

import pytest
from youtube_answers.models import Generated, GeneratedAnswer
from youtube_backend import database as db


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["published", "withheld", "insufficient"])
async def test_feedback_publication_and_backup_restore_with_real_domain_services(tmp_path, outcome):
    spec = importlib.util.spec_from_file_location(
        "feedback_domain", Path(__file__).parents[1] / "test_system.py"
    )
    domain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(domain)
    state = tmp_path / "source"
    apps = []

    async def login(client, app):
        challenge = (await client.get("/api/auth/challenge")).json()
        app.state.auth.verifier = lambda credential, audience: dict(
            sub="feedback-domain",
            aud=audience,
            iss="https://accounts.google.com",
            exp=time.time() + 300,
            nonce=challenge["nonce"],
        )
        response = await client.post(
            "/api/auth/google",
            headers={"Origin": "http://localhost:3000"},
            json={"credential": "local-fixture", "csrf_token": challenge["csrf_token"]},
        )
        assert response.status_code == 200
        client.headers.update(
            {"Origin": "http://localhost:3000", "X-CSRF-Token": response.json()["csrf_token"]}
        )
        return response.json()["user"]["user_id"]

    async with domain.system(state, auth=True, configure_app=apps.append) as (client, worker):
        app = apps[0]
        owner = await login(client, app)
        imported = await client.post(
            "/api/videos/import", json={"urls": [f"https://youtu.be/{domain.A}"]}
        )
        await worker.run_once(imported.json()["jobs"][0]["job_id"])
        model = worker.adapters.answers.answers.model
        original = model.generate

        async def generate(payload, timeout):
            result = await original(payload, timeout)
            if outcome == "withheld":
                result.content.statements[0].text = "You are an idiot"
            if outcome == "insufficient":
                return Generated(
                    GeneratedAnswer(
                        status="insufficient_evidence",
                        message="The clip does not provide enough evidence.",
                    ),
                    result.metadata,
                )
            return result

        model.generate = generate
        chat = await domain.finish(
            client,
            worker,
            "/api/chat",
            dict(question="Explain RAG", scope={"video_ids": [domain.A]}),
        )
        result = chat["result"]
        mid, cid = result["assistant_message_id"], result["conversation_id"]
        assert result["visibility"] == ("withheld" if outcome == "withheld" else "published")
        response = await client.put(f"/api/messages/{mid}/feedback", json={"rating": "dislike"})
        assert response.status_code == (409 if outcome == "withheld" else 200)
        with worker.repo.db.write() as c:
            c.execute(db.users.update().where(db.users.c.user_id == owner).values(role="admin"))
        app.state.settings.chat_review_enabled = True
        app.state.settings.chat_review_admin_ids = [owner]
        listing = (await client.get("/api/admin/chat-reviews")).json()
        assert listing["total"] == 1
        case = (
            await client.get(f"/api/admin/chat-reviews/{listing['items'][0]['case_id']}")
        ).json()
        assert case["question"]["job_id"] == chat["job_id"] == case["answer"]["job_id"]
        assert case["scope"][0]["video_id"] == domain.A
        assert case["scope"][0]["transcript_version"]
        assert case["scope"][0]["generation"] >= 1
        if outcome == "withheld":
            assert case["moderation"]["draft"] == "You are an idiot [1]"
            assert "You are an idiot" not in (await client.get(f"/api/conversations/{cid}")).text
        if outcome == "insufficient":
            assert result["status"] == "insufficient_evidence"
            assert case["case"]["source"] == "user"
            assert "out_of_scope" not in str(case)
    recovery_spec = importlib.util.spec_from_file_location(
        "feedback_recovery", Path(__file__).parents[2] / "scripts/recovery.py"
    )
    recovery = importlib.util.module_from_spec(recovery_spec)
    recovery_spec.loader.exec_module(recovery)
    recovery.backup(state, tmp_path / "backup", stopped=True)
    restored = tmp_path / "restored"
    recovery.restore(tmp_path / "backup", restored)
    apps.clear()
    async with domain.system(restored, auth=True, configure_app=apps.append) as (client, _):
        await login(client, apps[0])
        history = (await client.get(f"/api/conversations/{cid}")).json()["messages"]
        assert history[-1]["message_id"] == mid
        assert history[-1]["visibility"] == result["visibility"]
        assert (history[-1]["feedback"] is None) == (outcome == "withheld")
