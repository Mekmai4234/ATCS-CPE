"""Persisted-result reuse guards; no provider or duplicate publication involved."""

import asyncio
import time

import pytest
import sqlalchemy as sa
from test_identity import VIDEO, login, ready
from test_identity import identity as identity

from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError, LeaseLost
from youtube_backend.integrations import ExecutionContext
from youtube_backend.schemas import ChatRequest

KEY = "a" * 64


def setup(env):
    client, _ = login(env, "a")
    ready(env, client)
    body = {"question": "RAG", "scope": {"video_ids": [VIDEO]}}
    original = client.post("/api/chat", json=body).json()["job_id"]
    asyncio.run(env.worker.run_once(original))
    with env.db.write() as c:
        previous = (
            c.execute(sa.select(db.jobs).where(db.jobs.c.job_id == original)).mappings().one()
        )
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == original)
            .values(payload=dict(previous["payload"], answer_reuse_key=KEY))
        )
    return client, body, original


def context(env, client, body):
    token = actor_id.set(client.get("/api/auth/me").json()["user"]["user_id"])
    try:
        job_id = env.repo.enqueue("chat", ChatRequest.model_validate(body).model_dump(mode="json"))[
            "job_id"
        ]
    finally:
        actor_id.reset(token)
    job = env.repo.claim(job_id)
    return ExecutionContext(env.repo, job_id, job["lease_token"], job["deadline_at"], env.settings)


@pytest.mark.parametrize(
    "change", [None, "question", "history", "execution", "metadata", "null_metadata", "old"]
)
def test_reuse_validates_frozen_context_and_corrupt_metadata(identity, change):
    env = identity
    client, body, original = setup(env)
    with env.db.write() as c:
        previous = dict(
            c.execute(sa.select(db.jobs).where(db.jobs.c.job_id == original)).mappings().one()
        )
        payload, result = dict(previous["payload"]), dict(previous["result"])
        if change == "history":
            payload["history"] = [{"role": "user", "content": "unrelated"}]
        if change == "execution":
            payload["execution"] = {"provider": "different"}
        if change == "metadata":
            result["provider_metadata"] = {"provider": "fixture"}
        if change == "null_metadata":
            result["provider_metadata"] = None
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == original)
            .values(
                payload=payload,
                result=result,
                updated_at=time.time() - (90000 if change == "old" else 0),
            )
        )
    ctx = context(env, client, dict(body, question="new") if change == "question" else body)
    answer = ctx.saved_answer(KEY)
    assert (answer is not None) == (change is None)
    if answer:
        assert "assistant_message_id" not in answer and "conversation_id" not in answer
        assert answer["answer"] == previous["result"]["answer"]


def test_reuse_is_owner_scoped_and_revocation_remains_authoritative(identity):
    env = identity
    client, body, _ = setup(env)
    other, _ = login(env, "b")
    ready(env, other)
    assert context(env, other, body).saved_answer(KEY) is None
    ctx = context(env, client, body)
    assert ctx.saved_answer(KEY)
    with env.db.write() as c:
        c.execute(db.user_videos.delete())
    with pytest.raises((AppError, LeaseLost)):
        ctx.saved_answer(KEY)


def test_reuse_key_rejects_non_hex_before_lookup(identity):
    client, body, _ = setup(identity)
    ctx = context(identity, client, body)
    with pytest.raises(AppError, match="reuse key"):
        ctx.saved_answer("z" * 64)
