"""Independent API acceptance: actual identity/CSRF, durable worker and privacy."""

import asyncio

import sqlalchemy as sa
from youtube_backend import database as db
from youtube_backend.moderation import purge_expired

VIDEO = "dQw4w9WgXcQ"


def published(env):
    imported = env.a.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
    job_id = imported.json()["jobs"][0]["job_id"]
    asyncio.run(env.worker.run_once(job_id))
    response = env.a.post("/api/chat", json={"question": "RAG", "scope": {"video_ids": [VIDEO]}})
    assert response.status_code == 200, response.text
    env.app.state.settings.chat_review_enabled = True
    env.app.state.settings.chat_review_admin_ids = [env.users["admin"]["user_id"]]
    return response.json()


def test_feedback_lifecycle_revocation_and_erasure_leave_no_readable_review_copy(identities):
    env = identities
    result = published(env)
    mid, cid = result["assistant_message_id"], result["conversation_id"]
    with env.db.write() as c:
        c.execute(
            db.v2["reservations"]
            .insert()
            .values(
                reservation_id="retention-ledger",
                project="fixture",
                policy_digest="fixture-policy",
                bucket="shared",
                model="fixture",
                endpoint="generateContent",
                role="chat",
                owner_id=env.users["a"]["user_id"],
                job_id=result["job_id"],
                lease_token="ended",
                call_key="fixture-already-settled",
                state="consumed",
                tokens=123,
                created_at=1,
                expires_at=2,
                returned_allowlist=[],
            )
        )
    path = f"/api/messages/{mid}/feedback"
    feedback = dict(rating="dislike", reason="citation_mismatch", comment="<img onerror=alert(1)>")
    first = env.a.put(path, json=feedback)
    assert first.status_code == 200
    assert env.a.put(path, json=feedback).json() == first.json()
    assert env.b.put(path, json={"rating": "like"}).status_code == 404
    assert env.suspended.get(path).status_code == 401
    assert env.a.put(path, json=feedback, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    env.a, _ = env.login("a", client=env.a)
    assert (
        env.a.get(f"/api/conversations/{cid}").json()["messages"][-1]["feedback"]
        == first.json()["feedback"]
    )
    listing = env.admin.get("/api/admin/chat-reviews", params={"limit": 1}).json()
    case_id = listing["items"][0]["case_id"]
    detail = env.admin.get(f"/api/admin/chat-reviews/{case_id}").json()
    assert detail["question"]["job_id"] == detail["answer"]["job_id"] == result["job_id"]
    assert detail["feedback"]["comment"] == feedback["comment"]
    assert detail["scope"][0]["video_id"] == VIDEO and detail["citations"]
    assert env.admin.get(f"/api/conversations/{cid}").status_code == 404
    with env.db.read() as c:
        before = c.scalar(sa.select(sa.func.count()).select_from(db.v2["reservations"]))
    assert env.a.delete(f"/api/conversations/{cid}").status_code == 200
    assert env.admin.get(f"/api/admin/chat-reviews/{case_id}").status_code == 404
    assert env.admin.get(f"/api/admin/chat-messages/{mid}").status_code == 404
    assert env.a.get(path).status_code == 404
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.v2["reservations"])) == before
        assert before == 1
        assert c.scalar(sa.select(db.v2["reservations"].c.tokens)) == 123
        for table in db.review.values():
            assert c.scalar(sa.select(sa.func.count()).select_from(table)) == 0
    assert purge_expired(env.app.state.repository) == 0


def test_direct_input_cannot_create_job_or_invoke_provider_and_blocks_are_reviewable(identities):
    env = identities
    result = published(env)

    async def forbidden(*args):
        raise AssertionError("Denied input reached the answer provider")

    env.app.state.adapters.adapter.answer = forbidden
    with env.db.read() as c:
        before = c.scalar(sa.select(sa.func.count()).select_from(db.jobs))
    request = dict(
        question="มึง\u200bโง่",
        scope={"video_ids": [VIDEO]},
        conversation_id=result["conversation_id"],
    )
    assert env.a.post("/api/chat", json=request).status_code == 422
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == before
    listing = env.admin.get("/api/admin/chat-reviews", params={"q": "โง่"}).json()
    assert listing["total"] == 1
    case = listing["items"][0]
    assert case["question_excerpt"] == request["question"]
    assert env.admin.get("/api/admin/chat-reviews", params={"after": "nan"}).status_code == 422
    detail = env.admin.get(f"/api/admin/chat-reviews/{case['case_id']}").json()
    assert detail["moderation"]["direction"] == "input"
    assert detail["moderation"]["visible_to_user"] is False
    assert "answer" not in detail
    assert env.a.delete(f"/api/conversations/{result['conversation_id']}").status_code == 200
    assert env.admin.get(f"/api/admin/chat-reviews/{case['case_id']}").status_code == 404
