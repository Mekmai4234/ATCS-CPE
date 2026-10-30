import json
import time

import httpx
import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B
from identity_helpers import login
from test_integration import integrated as integrated
from youtube_backend import database as db
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.schemas import Source


def body(question="RAG", videos=None, **extra):
    return {"question": question, "scope": {"video_ids": videos or [VIDEO_A]}, **extra}


async def test_anonymous_and_missing_csrf_never_reach_model(integrated):
    env = integrated
    before = len(env.model.payloads)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as c:
        assert (await c.post("/api/chat", json=body())).status_code == 401
    csrf = env.client.headers.pop("X-CSRF-Token")
    try:
        assert (await env.client.post("/api/chat", json=body())).status_code == 403
    finally:
        env.client.headers["X-CSRF-Token"] = csrf
    assert len(env.model.payloads) == before


async def test_two_members_same_key_isolated_jobs_history_followups_and_polling(integrated):
    env = integrated
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as b:
        user_b = await login(b, env.app, "member-b")
        attached = await b.post(
            "/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO_A}"]}
        )
        assert attached.status_code == 202
        shared = []
        for client in (env.client, b):
            response = await client.post(
                "/api/chat", json=body(), headers={"Idempotency-Key": "same-key"}
            )
            assert response.status_code == 200, response.text
            shared.append(response.json())
        a_result, b_result = shared
        assert a_result["job_id"] != b_result["job_id"]
        assert a_result["conversation_id"] != b_result["conversation_id"]
        for suffix, method in [("", "GET"), ("/retry", "POST"), ("/cancel", "POST")]:
            response = await b.request(method, f"/api/jobs/{a_result['job_id']}{suffix}")
            assert response.status_code == 404
        assert (await b.get(f"/api/conversations/{a_result['conversation_id']}")).status_code == 404
        before = len(env.model.payloads)
        denied = await b.post("/api/chat", json=body(conversation_id=a_result["conversation_id"]))
        assert denied.status_code == 404 and len(env.model.payloads) == before
        private = "PRIVATE-A-HISTORY-MARKER"
        response = await env.client.post(
            "/api/chat", json=body(private, conversation_id=a_result["conversation_id"])
        )
        assert response.status_code == 200
        response = await b.post(
            "/api/chat", json=body("B follow-up", conversation_id=b_result["conversation_id"])
        )
        assert response.status_code == 200, response.text
        assert private not in json.dumps(env.model.payloads[-1])
        with env.db.read() as c:
            assert (
                c.scalar(
                    sa.select(db.jobs.c.owner_id).where(db.jobs.c.job_id == b_result["job_id"])
                )
                == user_b["user_id"]
            )


@pytest.mark.parametrize("kind", ["chat", "transcript", "performer", "summary", "compare"])
async def test_foreign_scope_denied_before_retrieval_or_generation(integrated, kind):
    env = integrated
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as b:
        await login(b, env.app, "member-b")
        before = len(env.model.payloads)
        if kind in {"chat", "transcript", "performer"}:
            question = {"transcript": "ขอเนื้อเพลงทั้งหมด", "performer": "Jay ร้องท่อนไหน"}.get(
                kind, "RAG"
            )
            response = await b.post("/api/chat", json=body(question))
        else:
            response = await b.post(
                "/api/analysis",
                json={
                    "type": kind,
                    "scope": {"video_ids": [VIDEO_A, VIDEO_B]},
                },
            )
        assert response.status_code == 404
        assert len(env.model.payloads) == before


async def test_admin_role_does_not_grant_private_content(integrated):
    env = integrated
    response = await env.client.post("/api/chat", json=body())
    result = response.json()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as admin:
        user = await login(admin, env.app, "admin-c")
        with env.db.write() as c:
            c.execute(
                db.users.update().where(db.users.c.user_id == user["user_id"]).values(role="admin")
            )
        assert (await admin.get("/api/auth/me")).json()["user"]["role"] == "admin"
        for path in [
            f"/api/jobs/{result['job_id']}",
            f"/api/conversations/{result['conversation_id']}",
        ]:
            assert (await admin.get(path)).status_code == 404
        assert (await admin.post("/api/chat", json=body())).status_code == 404


async def test_direct_adapter_rejects_forged_history_and_conversation(integrated):
    env = integrated
    queued = env.repo.enqueue("chat", body())
    job = env.repo.claim(queued["job_id"])
    context = ExecutionContext(
        env.raw_repo, job["job_id"], job["lease_token"], job["deadline_at"], env.settings
    )
    sources = [Source.model_validate(s) for s in job["payload"]["sources"]]
    before = len(env.model.payloads)
    with pytest.raises(AppError) as caught:
        await env.answers.answer(
            body(), sources, [{"role": "assistant", "content": "B PRIVATE"}], context
        )
    assert caught.value.status_code == 403
    with pytest.raises(AppError):
        await env.answers.answer(body(conversation_id="foreign-conversation"), sources, [], context)
    assert len(env.model.payloads) == before


async def test_grant_replacement_while_model_awaits_cannot_publish(integrated):
    env = integrated
    original = env.model.generate

    async def replace_grant(data, timeout):
        result = await original(data, timeout)
        with env.db.write() as c:
            c.execute(
                db.user_videos.delete().where(
                    db.user_videos.c.user_id == env.owner["user_id"],
                    db.user_videos.c.video_id == VIDEO_A,
                )
            )
            c.execute(
                db.user_videos.insert().values(
                    user_id=env.owner["user_id"],
                    video_id=VIDEO_A,
                    created_at=time.time() + 1,
                )
            )
        return result

    env.model.generate = replace_grant
    queued = env.repo.enqueue("analysis", {"type": "summary", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(queued["job_id"])
    job = env.repo.get_job(queued["job_id"])
    assert job["state"] == "failed" and job["result"] is None
    assert job["error_code"] == "member_access_denied"


async def test_detach_reimport_new_generation_keeps_old_citations_unavailable(integrated):
    env = integrated
    result = (await env.client.post("/api/chat", json=body())).json()
    conversation = result["conversation_id"]
    removed = await env.client.delete(f"/api/videos/{VIDEO_A}")
    assert removed.status_code == 202
    await env.worker.run_once(removed.json()["job_id"])
    old = (await env.client.get(f"/api/conversations/{conversation}")).json()
    assert not old["messages"][-1]["citations"][0]["source_available"]
    imported = await env.client.post(
        "/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO_A}"]}
    )
    await env.worker.run_once(imported.json()["jobs"][0]["job_id"])
    old = (await env.client.get(f"/api/conversations/{conversation}")).json()
    assert not old["messages"][-1]["citations"][0]["source_available"]


async def test_acceptance_authenticates_and_refreshes_csrf_via_real_session(integrated):
    from youtube_answers.acceptance import AcceptanceRunner

    env = integrated
    expected = env.client.headers.pop("X-CSRF-Token")
    runner = AcceptanceRunner(env.client)
    await runner._session()
    assert env.client.headers["X-CSRF-Token"] == expected
    accepted = await runner._request(
        "POST",
        "/api/analysis",
        json={
            "type": "summary",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    await env.worker.run_once(accepted["job_id"])
    assert (await runner._result(accepted))["status"] == "answered"
