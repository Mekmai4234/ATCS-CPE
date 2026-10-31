"""PR #39 review regressions: actual API/session/worker, isolated fixture database."""

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from test_chat_feedback import VIDEO, published
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.moderation import purge_expired
from youtube_backend.schemas import ChatRequest


def request():
    return ChatRequest(question="damn explain RAG", scope={"video_ids": [VIDEO]}).model_dump(
        mode="json"
    )


def queued(env, ticket, key):
    token = actor_id.set(env.users["a"]["user_id"])
    try:
        return env.app.state.repository.enqueue(
            "chat", dict(request(), moderation_token=ticket), key
        )
    finally:
        actor_id.reset(token)


def counts(env):
    with env.db.read() as c:
        return {
            t.name: c.scalar(sa.select(sa.func.count()).select_from(t))
            for t in (db.jobs, db.review["events"], db.v2["reservations"])
        }


def test_completed_acknowledged_request_replays_after_expiry_without_resubmission(identities):
    env = identities
    published(env)
    body = request()
    ticket = env.a.post("/api/chat/check", json=body).json()
    submitted = dict(body, moderation_token=ticket["acknowledgment_token"])
    calls = []
    original = env.app.state.adapters.adapter.answer

    async def counted(*args):
        calls.append(1)
        return await original(*args)

    env.app.state.adapters.adapter.answer = counted
    headers = {"Idempotency-Key": "review07-replay"}
    completed = env.a.post("/api/chat", json=submitted, headers=headers)
    assert completed.status_code == 200
    with env.db.write() as c:
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.event_id == ticket["attempt_id"])
            .values(expires_at=time.time() - 1)
        )
    before = counts(env)
    for payload in (submitted, body):
        replay = env.a.post("/api/chat", json=payload, headers=headers)
        assert replay.status_code == 200 and replay.json() == completed.json()
    changed = env.a.post("/api/chat", json=dict(body, question="damn changed"), headers=headers)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"
    assert counts(env) == before and calls == [1]
    assert (
        env.a.post("/api/chat", json=submitted, headers={"Idempotency-Key": "new-work"}).status_code
        == 422
    )
    assert env.b.post("/api/chat", json=submitted, headers=headers).status_code == 422
    assert counts(env)["jobs"] == before["jobs"] and calls == [1]


def test_shared_ticket_creates_independent_proofs_and_deletion_cannot_cancel_other_work(identities):
    env = identities
    published(env)
    ticket = env.a.post("/api/chat/check", json=request()).json()
    first = queued(env, ticket["acknowledgment_token"], "queued-one")
    second = queued(env, ticket["acknowledgment_token"], "queued-two")
    before = counts(env)
    assert queued(env, ticket["acknowledgment_token"], "queued-one")["job_id"] == first["job_id"]
    assert counts(env) == before
    first_id, second_id = [job["payload"]["moderation_event_id"] for job in (first, second)]
    assert len({first_id, second_id, ticket["attempt_id"]}) == 3
    assert env.a.post(f"/api/jobs/{second['job_id']}/cancel").status_code == 200
    assert env.a.delete(f"/api/conversations/{second['conversation_id']}").status_code == 200
    with env.db.write() as c:
        proof = (
            c.execute(
                sa.select(db.review["events"]).where(db.review["events"].c.event_id == first_id)
            )
            .mappings()
            .one()
        )
        assert proof["job_id"] == first["job_id"]
        assert proof["owner_id"] == env.users["a"]["user_id"]
        assert proof["acknowledged_at"] <= proof["expires_at"]
        original = (
            c.execute(
                sa.select(db.review["events"]).where(
                    db.review["events"].c.event_id == ticket["attempt_id"]
                )
            )
            .mappings()
            .one()
        )
        assert original["job_id"] is None and original["acknowledged_at"] is None
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.event_id == ticket["attempt_id"])
            .values(expires_at=time.time() - 1)
        )
    asyncio.run(env.worker.run_once(first["job_id"]))
    assert env.a.get(f"/api/jobs/{first['job_id']}").json()["state"] == "completed"
    assert env.b.get(f"/api/jobs/{first['job_id']}").status_code == 404
    assert counts(env)["gemini_reservations"] == before["gemini_reservations"]


def test_worker_rejects_another_jobs_proof_even_with_matching_owner_and_text(identities):
    env = identities
    published(env)
    ticket = env.a.post("/api/chat/check", json=request()).json()
    first, second = [queued(env, ticket["acknowledgment_token"], key) for key in ("one", "two")]
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == first["job_id"])
            .values(
                payload=dict(
                    first["payload"], moderation_event_id=second["payload"]["moderation_event_id"]
                )
            )
        )
    calls = []

    async def forbidden(*args):
        calls.append(1)
        raise AssertionError("Mismatched execution proof reached provider")

    env.app.state.adapters.adapter.answer = forbidden
    asyncio.run(env.worker.run_once(first["job_id"]))
    result = env.a.get(f"/api/jobs/{first['job_id']}").json()
    assert result["state"] == "failed" and result["error_code"] == "moderation_blocked"
    assert not calls


@pytest.mark.parametrize("direction", ["input", "output"])
def test_expired_moderation_case_cannot_reveal_or_edit_copied_notes_before_sweep(
    identities, direction
):
    env = identities
    safe = published(env)
    if direction == "input":
        assert (
            env.a.post("/api/chat", json=dict(request(), question="You are an idiot")).status_code
            == 422
        )
    else:
        original = env.app.state.adapters.adapter.answer

        async def unsafe(*args):
            result = await original(*args)
            return result.model_copy(update={"answer": "You are an idiot"})

        env.app.state.adapters.adapter.answer = unsafe
        withheld = env.a.post("/api/chat", json=dict(request(), question="Explain RAG evidence"))
        assert withheld.status_code == 200 and withheld.json()["visibility"] == "withheld"
    case = env.admin.get("/api/admin/chat-reviews").json()["items"][0]
    url = f"/api/admin/chat-reviews/{case['case_id']}"
    private = "PRIVATE EXPIRED CONTENT COPY / copied draft"
    assert env.admin.patch(url, json={"status": "in_review", "notes": private}).status_code == 200
    detail = env.admin.get(url).json()
    assert detail["case"]["notes"] == private
    event_id = detail["case"]["event_id"]
    with env.db.write() as c:
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.event_id == event_id)
            .values(content_expires_at=time.time() - 1)
        )
    for response in (
        env.admin.get(url),
        env.admin.patch(url, json={"status": "reviewed", "outcome": "confirmed"}),
    ):
        assert response.status_code == 404 and private not in response.text
    listing = env.admin.get("/api/admin/chat-reviews", params={"status": "all"})
    assert listing.json()["total"] == 0 and listing.json()["stats"]["pending"] == 0
    assert private not in listing.text
    for suffix in ("", "/context"):
        normal = env.admin.get(f"/api/admin/chat-messages/{safe['assistant_message_id']}{suffix}")
        assert normal.status_code == 200 and private not in normal.text
    assert purge_expired(env.app.state.repository) == 1
    assert env.admin.get(url).status_code == 404
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.review["cases"])) == 0
        assert private not in str(c.execute(sa.select(db.admin_audit)).mappings().all())


def test_resume_replays_existing_replacement_after_expiry_without_new_proof_or_provider(
    identities, tmp_path
):
    env = identities
    published(env)
    calls = []
    original = env.app.state.adapters.adapter.answer

    async def counted(*args):
        calls.append(1)
        return await original(*args)

    env.app.state.adapters.adapter.answer = counted
    settings = env.app.state.settings
    key = "synthetic-07-review-policy-key"
    settings.gemini_api_key = SecretStr(key)
    now = datetime.now(UTC)
    policy = dict(
        tier="free",
        project_ref="review07-fixture",
        verified_by="fixture-operator",
        evidence_ref="fixture-not-a-real-billing-check",
        key_sha256=hashlib.sha256(key.encode()).hexdigest(),
        verified_at=(now - timedelta(minutes=1)).isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat(),
        pools={"shared": dict(rpm=10, tpm=1000, rpd=20, user_rpm=10)},
        models=[
            dict(
                model=settings.llm_model,
                bucket="shared",
                endpoints=["generateContent"],
                returned_models=[settings.llm_model],
                roles=["chat"],
                image_capable=False,
            )
        ],
    )
    policy_file = tmp_path / "fixture-policy.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    settings.gemini_free_policy_file = str(policy_file)
    ticket = env.a.post("/api/chat/check", json=request()).json()
    stopped = queued(env, ticket["acknowledgment_token"], "stopped")
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == stopped["job_id"])
            .values(state="failed", retryable=True)
        )
    path = f"/api/jobs/{stopped['job_id']}/resume"
    assert env.a.post(path).status_code == 422  # New replacement still needs acknowledgement.
    first = env.a.post(path, json={"moderation_token": ticket["acknowledgment_token"]})
    assert first.status_code == 202, first.text
    with env.db.write() as c:
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.event_id == ticket["attempt_id"])
            .values(expires_at=time.time() - 1)
        )
    before = counts(env)
    for payload in ({}, {"moderation_token": ticket["acknowledgment_token"]}):
        replay = env.a.post(path, json=payload)
        assert replay.status_code == 202 and replay.json() == first.json()
    assert counts(env) == before
    assert not calls
    assert env.b.post(path).status_code == 404
    asyncio.run(env.worker.run_once(first.json()["job_id"]))
    replay = env.a.post(path)
    assert replay.status_code == 202 and replay.json()["job_id"] == first.json()["job_id"]
    assert replay.json()["state"] == "completed" and calls == [1]
    assert counts(env) == before
