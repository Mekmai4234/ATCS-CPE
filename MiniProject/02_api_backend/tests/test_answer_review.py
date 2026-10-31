"""Opt-in producer contract, attempt binding and atomic/private signal publication."""

import asyncio
import time

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from test_chat_review import admin, body, setup
from test_identity import identity

from youtube_backend import database as db
from youtube_backend.answer_review import AnswerReviewSignal, stage
from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError, LeaseLost
from youtube_backend.moderation import purge_expired

__all__ = ["identity"]
SIGNAL = dict(
    policy_version="chat-review-draft-v1",
    reason="insufficient_evidence",
    source="system_rule",
    confirmed=False,
)


@pytest.mark.parametrize(
    "change",
    [
        {"policy_version": "chat-local-v1"},
        {"confirmed": True},
        {"source": "user"},
        {"producer": "01_web_app"},
        {"reason": "out_of_scope"},
        {"answer": "private"},
    ],
)
def test_signal_does_not_accept_another_policy_a_verdict_or_private_text(change):
    with pytest.raises(ValidationError):
        AnswerReviewSignal.model_validate(dict(SIGNAL, **change))


@pytest.mark.parametrize("withhold", [False, True])
def test_signal_is_private_metadata_and_does_not_control_publication(identity, withhold):
    env = identity
    client, _ = setup(env)
    original = env.app.state.adapters.adapter.answer

    async def producing(request, sources, history, context):
        context.review_signals([SIGNAL, SIGNAL])
        context.review_signals([SIGNAL])
        with env.db.read() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(db.review["cases"])) == 0
        result = await original(request, sources, history, context)
        return result.model_copy(update={"answer": "You are an idiot"}) if withhold else result

    env.app.state.adapters.adapter.answer = producing
    response = client.post("/api/chat", json=body())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["visibility"] == ("withheld" if withhold else "published")
    assert "review_signal" not in response.text
    assert "chat-review-draft-v1" not in client.get(f"/api/jobs/{result['job_id']}").text
    assert (
        "chat-review-draft-v1"
        not in client.get(f"/api/conversations/{result['conversation_id']}").text
    )
    reviewer, _ = admin(env)
    listing = reviewer.get(
        "/api/admin/chat-reviews", params={"label": "insufficient_evidence"}
    ).json()
    assert listing["total"] == 1
    case_id = listing["items"][0]["case_id"]
    detail = reviewer.get(f"/api/admin/chat-reviews/{case_id}").json()
    assert detail["review_signal"]["producer"] == "05_ai_answers_analysis"
    assert detail["review_signal"]["confirmed"] is False
    assert detail["review_signal"]["publication_effect"] == "none"
    assert detail["case"]["outcome"] is None and detail["case"]["source"] == "system"
    assert detail["moderation"]["draft"] is None
    assert detail["visibility"] == result["visibility"]
    assert client.get(f"/api/admin/chat-reviews/{case_id}").status_code == 403
    with env.db.write() as c:
        c.execute(
            db.review["events"]
            .update()
            .where(db.review["events"].c.policy_version == SIGNAL["policy_version"])
            .values(content_expires_at=time.time() - 1)
        )
    assert reviewer.get(f"/api/admin/chat-reviews/{case_id}").status_code == 404
    assert purge_expired(env.repo) >= 1
    assert client.delete(f"/api/conversations/{result['conversation_id']}").status_code == 200


def test_stale_attempt_cannot_stage_or_publish_signals(identity):
    env = identity
    client, user = setup(env)
    token = actor_id.set(user["user_id"])
    try:
        job = env.repo.enqueue("chat", body())
    finally:
        actor_id.reset(token)
    first = env.repo.claim(job["job_id"])
    stage(env.repo, job["job_id"], first["lease_token"], [SIGNAL])
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == job["job_id"])
            .values(state="queued", lease_token=None, lease_until=None)
        )
    with pytest.raises(LeaseLost):
        stage(env.repo, job["job_id"], first["lease_token"], [SIGNAL])
    # The next attempt returns normally without a signal; old pending metadata is discarded.
    asyncio.run(env.worker.run_once(job["job_id"]))
    assert client.get(f"/api/jobs/{job['job_id']}").json()["state"] == "completed"
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.review["cases"])) == 0
        assert (
            c.scalar(
                sa.select(sa.func.count())
                .select_from(db.review["events"])
                .where(db.review["events"].c.action == "pending_sig")
            )
            == 0
        )


def test_cancelled_job_never_publishes_staged_signal(identity):
    env = identity
    client, user = setup(env)
    token = actor_id.set(user["user_id"])
    try:
        job = env.repo.enqueue("chat", body())
    finally:
        actor_id.reset(token)
    running = env.repo.claim(job["job_id"])
    stage(env.repo, job["job_id"], running["lease_token"], [SIGNAL])
    assert client.post(f"/api/jobs/{job['job_id']}/cancel").status_code == 200
    with pytest.raises(AppError) as rejected:
        env.repo.finish(
            job["job_id"], running["lease_token"], {"answer": "must not publish", "citations": []}
        )
    assert rejected.value.code == "cancelled"
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.review["cases"])) == 0
