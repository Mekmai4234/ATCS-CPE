"""Persisted feedback, audited access, and guards through actual API/worker paths."""

import asyncio
import time

import pytest
import sqlalchemy as sa
from alembic import command
from test_free_tier import budget
from test_identity import VIDEO, identity, login, ready

from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.database import Database
from youtube_backend.migration import alembic_config, upgrade_database
from youtube_backend.moderation import NEUTRAL_ANSWER, classify, normalize, purge_expired
from youtube_backend.repository import Repository
from youtube_backend.schemas import ChatRequest

__all__ = ["identity", "budget"]


def setup(env):
    client, user = login(env, "a")
    ready(env, client)
    env.settings.chat_review_enabled = True
    return client, user


def body(question="What is RAG?", **extra):
    return dict(question=question, scope={"video_ids": [VIDEO]}, **extra)


def answer(client, **extra):
    response = client.post("/api/chat", json=body(**extra))
    assert response.status_code == 200, response.text
    return response.json()


def admin(env):
    client, user = login(env, "reviewer")
    with env.db.write() as c:
        c.execute(
            db.users.update().where(db.users.c.user_id == user["user_id"]).values(role="admin")
        )
    env.settings.chat_review_admin_ids = [user["user_id"]]
    return client, user


def test_feedback_idempotency_edit_withdraw_history_and_no_provider_calls(identity):
    env = identity
    client, _ = setup(env)
    result = answer(client)
    mid = result["assistant_message_id"]
    path = f"/api/messages/{mid}/feedback"
    first = client.put(path, json={"rating": "dislike"}).json()
    assert first["feedback"]["revision"] == 1
    assert client.put(path, json={"rating": "dislike"}).json() == first
    details = dict(rating="dislike", reason="incorrect", comment="<script>alert(1)</script>")
    assert client.put(path, json=details).json()["feedback"]["revision"] == 2
    history = client.get(f"/api/conversations/{result['conversation_id']}").json()["messages"]
    assert history[-1]["message_id"] == mid
    assert history[-1]["feedback"]["comment"] == details["comment"]
    assert (
        client.get(f"/api/jobs/{result['job_id']}").json()["result"]["assistant_message_id"] == mid
    )
    assert client.put(path, json={"rating": "like"}).json()["feedback"]["revision"] == 3
    assert client.delete(path).json()["feedback"] is None
    assert client.delete(path).status_code == 200
    assert client.get(path).json()["feedback"] is None
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.review["cases"])) == 0
        assert c.scalar(sa.select(sa.func.count()).select_from(db.v2["reservations"])) == 0


def test_feedback_ownership_csrf_wrong_role_and_invalid_payload(identity):
    env = identity
    client, _ = setup(env)
    result = answer(client)
    path = f"/api/messages/{result['assistant_message_id']}/feedback"
    other, _ = login(env, "b")
    for method in ("get", "delete", "put"):
        response = other.request(method, path, json={"rating": "like"} if method == "put" else None)
        assert response.status_code == 404
    assert (
        client.put(path, json={"rating": "like"}, headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    for payload in (
        {"rating": "bad"},
        {"rating": "dislike", "comment": "x" * 501},
        {"rating": "like", "comment": "no"},
        {"rating": "dislike", "reason": "bad"},
    ):
        assert client.put(path, json=payload).status_code == 422
    messages = client.get(f"/api/conversations/{result['conversation_id']}").json()["messages"]
    assert (
        client.put(
            f"/api/messages/{messages[0]['message_id']}/feedback", json={"rating": "like"}
        ).status_code
        == 409
    )


def test_review_exact_pair_filters_transition_audit_and_immediate_revocation(identity):
    env = identity
    client, user = setup(env)
    first = answer(client)
    second = answer(
        client, question="A second RAG question", conversation_id=first["conversation_id"]
    )
    mid = second["assistant_message_id"]
    client.put(f"/api/messages/{mid}/feedback", json={"rating": "dislike", "reason": "incorrect"})
    reviewer, review_user = admin(env)
    url = "/api/admin/chat-reviews"
    assert client.get(url).status_code == 403
    env.settings.chat_review_enabled = False
    assert reviewer.get(url).status_code == 403
    env.settings.chat_review_enabled = True
    listing = reviewer.get(url, params={"q": "second", "rating": "dislike", "limit": 1}).json()
    assert listing["total"] == 1 and listing["stats"]["dislike"] == 1
    assert user["email"] not in str(listing)
    assert listing["items"][0]["question_excerpt"] == "A second RAG question"
    assert reviewer.get(url, params={"q": "missing"}).json()["total"] == 0
    assert reviewer.get(url, params={"q": "%"}).json()["total"] == 0
    assert reviewer.get(url, params={"offset": 1}).json()["items"] == []
    case_id = listing["items"][0]["case_id"]
    detail = reviewer.get(f"{url}/{case_id}").json()
    assert detail["question"]["job_id"] == second["job_id"] == detail["answer"]["job_id"]
    assert detail["question"]["content"] == "A second RAG question"
    assert detail["case"]["source"] == "user" and detail["case"]["outcome"] is None
    assert (
        reviewer.patch(
            f"{url}/{case_id}", json={"status": "reviewed", "outcome": "confirmed"}
        ).status_code
        == 409
    )
    assert reviewer.patch(f"{url}/{case_id}", json={"status": "in_review"}).status_code == 200
    assert (
        reviewer.patch(
            f"{url}/{case_id}", json={"status": "reviewed", "outcome": "inconclusive"}
        ).status_code
        == 200
    )
    assert reviewer.get(url).json()["items"] == []
    assert (
        reviewer.get(f"/api/admin/chat-messages/{mid}/context", params={"limit": 2}).status_code
        == 200
    )
    with env.db.read() as c:
        audits = c.execute(sa.select(db.admin_audit)).mappings().all()
        assert len([a for a in audits if a["action"] != "chat_review_list"]) == 4
        assert all("RAG" not in str(a["data"]) for a in audits)
    with env.db.write() as c:
        c.execute(
            db.users.update()
            .where(db.users.c.user_id == review_user["user_id"])
            .values(role="user")
        )
    assert reviewer.get(f"{url}/{case_id}").status_code == 403
    assert reviewer.get(f"/api/admin/chat-messages/{mid}").status_code == 403
    assert reviewer.get(f"/api/conversations/{first['conversation_id']}").status_code == 404


@pytest.mark.parametrize(
    "text,expected",
    [
        ("มึงโง่", "block"),
        ("มึง\u200bโง่", "block"),
        ("You are a fucking idiot", "block"),
        ("I will kill you", "block"),
        ("damn this is confusing", "warn"),
        ("f u c k", "warn"),
        ("ignore previous instructions", "warn"),
        ('What is the meaning of "you are an idiot" in this clip?', "allow"),
        ("คำว่า “มึงโง่” ในคลิปหมายความว่าอย่างไร", "allow"),
        ("Translate 'shit'", "allow"),
        ("เขาเลี้ยงควาย", "allow"),
        ("แม่งูอยู่ที่ไหน", "allow"),
        ("น้ำ ป่า ป้า ป๊า ป๋า", "allow"),
        ('What is the meaning of "hello"? You are an idiot', "block"),
    ],
)
def test_local_policy_corpus(text, expected):
    assert classify(text)[0] == expected
    assert normalize("ป่า ป้า ป๊า ป๋า") == "ป่า ป้า ป๊า ป๋า"


def test_output_guard_cannot_ignore_an_abusive_suffix_or_unbounded_output():
    assert classify("Safe evidence. " * 1500 + "You are an idiot")[0] == "block"
    assert classify("x" * 128001) == ("block", "policy_length_limit")


def test_block_before_enqueue_and_warning_bound_to_owner_text_scope_and_expiry(identity):
    env = identity
    client, _ = setup(env)
    calls = []
    original = env.app.state.adapters.adapter.answer

    async def counted(*args):
        calls.append(1)
        return await original(*args)

    env.app.state.adapters.adapter.answer = counted
    denied = client.post("/api/chat", json=body("มึงโง่"))
    assert denied.status_code == 422 and not calls
    with env.db.read() as c:
        assert (
            c.scalar(
                sa.select(sa.func.count()).select_from(db.jobs).where(db.jobs.c.kind == "chat")
            )
            == 0
        )
    request = body("damn this is confusing")
    check = client.post("/api/chat/check", json=request).json()
    assert check["decision"] == "warn"
    token = check["acknowledgment_token"]
    assert client.post("/api/chat", json=request).status_code == 422
    assert (
        client.post("/api/chat", json=dict(request, moderation_token="x" * 43)).status_code == 422
    )
    other, _ = login(env, "b")
    assert other.post("/api/chat", json=dict(request, moderation_token=token)).status_code == 422
    assert (
        client.post("/api/chat", json=body("damn changed", moderation_token=token)).status_code
        == 422
    )
    response = client.post("/api/chat", json=dict(request, moderation_token=token))
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    with env.db.write() as c:
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.event_id == check["attempt_id"])
            .values(expires_at=time.time() - 1)
        )
    assert client.post("/api/chat", json=dict(request, moderation_token=token)).status_code == 422


def test_suppressed_output_never_published_or_rateable_audited_draft_retention_and_deletion(
    identity,
):
    env = identity
    client, _ = setup(env)
    original = env.app.state.adapters.adapter.answer

    async def unsafe(*args):
        result = await original(*args)
        return result.model_copy(update={"answer": "You are an idiot"})

    env.app.state.adapters.adapter.answer = unsafe
    result = answer(client)
    mid, cid = result["assistant_message_id"], result["conversation_id"]
    assert result["visibility"] == "withheld" and result["answer"] == NEUTRAL_ANSWER
    assert "You are an idiot" not in client.get(f"/api/jobs/{result['job_id']}").text
    assert "You are an idiot" not in client.get(f"/api/conversations/{cid}").text
    assert client.put(f"/api/messages/{mid}/feedback", json={"rating": "like"}).status_code == 409
    reviewer, _ = admin(env)
    case_id = reviewer.get("/api/admin/chat-reviews").json()["items"][0]["case_id"]
    path = f"/api/admin/chat-reviews/{case_id}"
    detail = reviewer.get(path).json()
    assert detail["moderation"]["draft"] == "You are an idiot"
    assert detail["moderation"]["visible_to_user"] is False
    with env.db.write() as c:
        c.execute(db.review["events"].update().values(content_expires_at=time.time() - 1))
    assert reviewer.get(path).status_code == 404
    assert purge_expired(env.repo) == 1
    assert reviewer.get(path).status_code == 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert client.get(f"/api/conversations/{cid}").status_code == 404
    assert reviewer.get(f"/api/admin/chat-messages/{mid}").status_code == 404
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.messages)) == 0


def test_migration_preserves_existing_data_and_refuses_lossy_downgrade(tmp_path, env):
    database = Database(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    upgrade_database(database, "0003")
    repo = Repository(database, env.settings)
    with database.write() as c:
        c.execute(db.conversations.insert().values(conversation_id="old", created_at=1))
        job = repo._new_job(c, "chat", {"request": body(), "sources": []}, conversation_id="old")
        c.execute(
            db.messages.insert().values(
                message_id="old-message",
                conversation_id="old",
                job_id=job["job_id"],
                role="user",
                content="Original Thai ป่า",
                scope=[],
                created_at=1,
            )
        )
    upgrade_database(database)
    database.check_schema()
    with database.read() as c:
        assert c.scalar(sa.select(db.messages.c.content)) == "Original Thai ป่า"
    with database.engine.begin() as c:
        command.downgrade(alembic_config(c), "0003")
    upgrade_database(database)
    with database.write() as c:
        c.execute(
            db.review["events"]
            .insert()
            .values(
                event_id="e",
                direction="input",
                action="block",
                reason="test",
                policy_version="v1",
                content="private",
                created_at=1,
                content_expires_at=2,
            )
        )
    with pytest.raises(RuntimeError, match="paired backup"), database.engine.begin() as c:
        command.downgrade(alembic_config(c), "0003")
    with database.read() as c:
        assert c.scalar(sa.select(db.messages.c.content)) == "Original Thai ป่า"
    database.close()


def test_worker_rechecks_legacy_queued_input_without_calling_provider(identity):
    env = identity
    client, user = setup(env)
    token = actor_id.set(user["user_id"])
    try:
        job = env.repo.enqueue("chat", body())
    finally:
        actor_id.reset(token)
    with env.db.write() as c:
        payload = dict(job["payload"])
        payload["request"] = body("You are an idiot")
        c.execute(db.jobs.update().where(db.jobs.c.job_id == job["job_id"]).values(payload=payload))

    async def forbidden(*args):
        pytest.fail("Blocked input must never reach the provider")

    env.app.state.adapters.adapter.answer = forbidden
    asyncio.run(env.worker.run_once(job["job_id"]))
    assert client.get(f"/api/jobs/{job['job_id']}").json()["error_code"] == "moderation_blocked"


def test_legacy_completed_result_resolves_id_without_rewriting_answer(identity):
    env = identity
    client, _ = setup(env)
    response = client.post("/api/chat", json=body(), headers={"Idempotency-Key": "legacy-id"})
    result = response.json()
    mid = result["assistant_message_id"]
    old = {
        k: v
        for k, v in result.items()
        if k not in {"assistant_message_id", "visibility", "moderation_policy_version", "feedback"}
    }
    with env.db.write() as c:
        c.execute(db.jobs.update().where(db.jobs.c.job_id == result["job_id"]).values(result=old))
    assert (
        client.get(f"/api/jobs/{result['job_id']}").json()["result"]["assistant_message_id"] == mid
    )
    replay = client.post("/api/chat", json=body(), headers={"Idempotency-Key": "legacy-id"})
    assert replay.status_code == 200 and replay.json()["assistant_message_id"] == mid
    assert replay.json()["answer"] == old["answer"]
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.messages)) == 2


def test_resume_requires_fresh_bound_ack_and_cannot_bypass_block(budget):
    env = budget
    job = env.repo.get_job(env.context.job_id, internal=True)
    request = ChatRequest.model_validate(body("damn this is confusing")).model_dump(mode="json")
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == job["job_id"])
            .values(
                payload=dict(job["payload"], request=request),
                state="failed",
                retryable=True,
                lease_token=None,
                lease_until=None,
            )
        )
    path = f"/api/jobs/{job['job_id']}/resume"
    assert env.client.post(path).status_code == 422
    check = env.client.post("/api/chat/check", json=request).json()
    response = env.client.post(path, json={"moderation_token": check["acknowledgment_token"]})
    assert response.status_code == 202, response.text
    assert (
        env.client.post(path, json={"moderation_token": check["acknowledgment_token"]}).json()
        == response.json()
    )
    with env.db.write() as c:
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.event_id == check["attempt_id"])
            .values(expires_at=time.time() - 1)
        )
        jobs_before = c.scalar(sa.select(sa.func.count()).select_from(db.jobs))
        events_before = c.scalar(sa.select(sa.func.count()).select_from(db.review["events"]))
    assert env.client.post(path).json() == response.json()
    assert (
        env.client.post(path, json={"moderation_token": check["acknowledgment_token"]}).json()
        == response.json()
    )
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == jobs_before
        assert (
            c.scalar(sa.select(sa.func.count()).select_from(db.review["events"])) == events_before
        )
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == job["job_id"])
            .values(
                payload=dict(job["payload"], request=dict(request, question="You are an idiot"))
            )
        )
    assert (
        env.client.post(path, json={"moderation_token": check["acknowledgment_token"]}).status_code
        == 409
    )


@pytest.mark.parametrize("remove_token", [False, True])
def test_review_replay_after_ack_expiry_is_read_only(identity, remove_token):
    env = identity
    client, _ = setup(env)
    request = body("damn explain RAG")
    check = client.post("/api/chat/check", json=request).json()
    submitted = dict(request, moderation_token=check["acknowledgment_token"])
    calls = []
    original = env.app.state.adapters.adapter.answer

    async def counted(*args):
        calls.append(1)
        return await original(*args)

    env.app.state.adapters.adapter.answer = counted
    headers = {"Idempotency-Key": "review-replay"}
    first = client.post("/api/chat", json=submitted, headers=headers)
    assert first.status_code == 200
    with env.db.write() as c:
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.event_id == check["attempt_id"])
            .values(expires_at=time.time() - 1)
        )
        jobs_before = c.scalar(sa.select(sa.func.count()).select_from(db.jobs))
        events_before = c.scalar(sa.select(sa.func.count()).select_from(db.review["events"]))
    replay = client.post("/api/chat", json=request if remove_token else submitted, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert len(calls) == 1
    conflict = client.post(
        "/api/chat", json=dict(submitted, question="Changed question"), headers=headers
    )
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
    )
    # The same payload without an existing key must still pass admission.
    assert (
        client.post(
            "/api/chat", json=submitted, headers={"Idempotency-Key": "new-work"}
        ).status_code
        == 422
    )
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == jobs_before
        # Only the denied NEW attempt creates a moderation event, never replay/conflict.
        assert (
            c.scalar(sa.select(sa.func.count()).select_from(db.review["events"]))
            == events_before + 1
        )


def test_review_shared_ticket_keeps_each_queued_job_proof_after_other_chat_erasure(identity):
    env = identity
    client, user = setup(env)
    request = ChatRequest.model_validate(body("damn explain RAG")).model_dump(mode="json")
    check = client.post("/api/chat/check", json=request).json()
    token = actor_id.set(user["user_id"])
    try:
        submitted = dict(request, moderation_token=check["acknowledgment_token"])
        first = env.repo.enqueue("chat", submitted, "first-queued")
        second = env.repo.enqueue("chat", submitted, "second-queued")
        assert env.repo.enqueue("chat", submitted, "first-queued")["job_id"] == first["job_id"]
    finally:
        actor_id.reset(token)
    assert first["payload"]["moderation_event_id"] != second["payload"]["moderation_event_id"]
    assert client.post(f"/api/jobs/{second['job_id']}/cancel").status_code == 200
    assert client.delete(f"/api/conversations/{second['conversation_id']}").status_code == 200
    with env.db.read() as c:
        proof = (
            c.execute(
                sa.select(db.review["events"]).where(
                    db.review["events"].c.event_id == first["payload"]["moderation_event_id"]
                )
            )
            .mappings()
            .one()
        )
        assert proof["job_id"] == first["job_id"]
    asyncio.run(env.worker.run_once(first["job_id"]))
    assert client.get(f"/api/jobs/{first['job_id']}").json()["state"] == "completed"


def test_review_expired_notes_are_unreadable_and_uneditable_before_purge(identity):
    env = identity
    client, _ = setup(env)
    assert client.post("/api/chat", json=body("You are an idiot")).status_code == 422
    reviewer, _ = admin(env)
    case = reviewer.get("/api/admin/chat-reviews").json()["items"][0]
    path = f"/api/admin/chat-reviews/{case['case_id']}"
    private = "PRIVATE EXPIRED CONTENT COPY"
    assert reviewer.patch(path, json={"status": "in_review", "notes": private}).status_code == 200
    assert reviewer.get(path).json()["case"]["notes"] == private
    with env.db.write() as c:
        c.execute(db.review["events"].update().values(content_expires_at=time.time() - 1))
    response = reviewer.get(path)
    assert response.status_code == 404 and private not in response.text
    assert (
        reviewer.patch(path, json={"status": "reviewed", "outcome": "confirmed"}).status_code == 404
    )
    listing = reviewer.get("/api/admin/chat-reviews", params={"status": "all"})
    assert listing.json()["total"] == 0 and private not in listing.text
    assert purge_expired(env.repo) == 1
    assert reviewer.get(path).status_code == 404
    with env.db.read() as c:
        assert private not in str(c.execute(sa.select(db.admin_audit)).mappings().all())


def test_ticket_expiring_during_enqueue_rolls_back_job_conversation_and_proof(
    identity, monkeypatch
):
    from youtube_backend import moderation

    env = identity
    client, _ = setup(env)
    request = body("damn explain RAG")
    ticket = client.post("/api/chat/check", json=request).json()
    original = moderation.admit

    def expires_before_bind(repo, body):
        ticket_id = original(repo, body)
        with repo.db.write() as c:
            c.execute(
                db.review["events"]
                .update()
                .where(db.review["events"].c.event_id == ticket_id)
                .values(expires_at=time.time() - 1)
            )
        return ticket_id

    monkeypatch.setattr(moderation, "admit", expires_before_bind)
    with env.db.read() as c:
        before = {
            table.name: c.scalar(sa.select(sa.func.count()).select_from(table))
            for table in (db.jobs, db.conversations, db.messages, db.review["events"])
        }
    assert (
        client.post(
            "/api/chat", json=dict(request, moderation_token=ticket["acknowledgment_token"])
        ).status_code
        == 422
    )
    with env.db.read() as c:
        for table in (db.jobs, db.conversations, db.messages, db.review["events"]):
            assert c.scalar(sa.select(sa.func.count()).select_from(table)) == before[table.name]


def test_liked_normal_answers_are_filtered_and_audited(identity):
    client, _ = setup(identity)
    result = answer(client)
    mid = result["assistant_message_id"]
    assert client.put(f"/api/messages/{mid}/feedback", json={"rating": "like"}).status_code == 200
    reviewer, _ = admin(identity)
    data = reviewer.get("/api/admin/chat-messages?rating=like").json()
    assert data["total"] == 1 and data["items"][0]["message_id"] == mid
    assert data["items"][0]["feedback"]["rating"] == "like"
    assert data["items"][0]["question_excerpt"] == "What is RAG?"
    assert reviewer.get("/api/admin/chat-messages?rating=dislike").json()["total"] == 0
    assert client.get("/api/admin/chat-messages?rating=like").status_code == 403
