import sqlalchemy as sa
from test_free_tier import budget, reserve
from test_identity import identity, login

from youtube_backend import database as db
from youtube_backend.quota import ProviderReply

__all__ = ["budget", "identity"]


def test_quota_is_member_private_and_admin_sees_only_aggregate_counts(budget):
    env = budget
    permit = reserve(env)
    env.broker.dispatch(env.context, permit)
    env.broker.settle(permit, reply=ProviderReply(None, 100, env.settings.llm_model))
    before = env.client.get("/api/quota")
    assert before.status_code == 200
    data = before.json()
    assert data["accounting_source"] == "local_ledger"
    assert data["provider_balance_verified"] is False
    assert data["pools"][0]["usage"]["requests_24h"] == 1
    assert "limits" not in data["pools"][0]
    assert env.client.get("/api/admin/quota").status_code == 403
    other, user = login(env, "b")
    assert other.get("/api/quota").json()["pools"][0]["usage"]["requests_24h"] == 0
    with env.db.write() as c:
        c.execute(
            db.users.update().where(db.users.c.user_id == user["user_id"]).values(role="admin")
        )
    admin = other.get("/api/admin/quota").json()
    assert admin["pools"][0]["remaining_requests_24h"] == 19
    encoded = str(admin)
    for secret in (
        env.user["user_id"],
        env.context.job_id,
        "fixture-free-project-key",
        "key_sha256",
        "project_ref",
    ):
        assert secret not in encoded
    assert before.headers["cache-control"] == "no-store"


def test_local_daily_wait_is_estimated_and_read_does_not_mutate_ledger(budget):
    env = budget
    env.policy["pools"]["shared"]["rpd"] = 1
    import json

    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    permit = reserve(env)
    env.broker.dispatch(env.context, permit)
    env.broker.settle(permit, reply=ProviderReply(None, 100, env.settings.llm_model))
    data = env.client.get("/api/quota").json()
    assert data["status"] == "waiting"
    blocker = data["pools"][0]["blockers"][0]
    assert blocker["reason"] == "local_daily_limit"
    assert blocker["time_source"] == "estimate" and "retry_at" not in blocker
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.v2["reservations"])) == 1


def test_missing_policy_and_anonymous_and_suspended_account(identity):
    env = identity
    assert env.transport.get("/api/quota").status_code == 401
    client, user = login(env, "a")
    assert client.get("/api/quota").json()["status"] == "unverified"
    with env.db.write() as c:
        c.execute(
            db.users.update()
            .where(db.users.c.user_id == user["user_id"])
            .values(status="suspended")
        )
    assert client.get("/api/quota").status_code == 401


def test_resume_reuses_replacement_and_keeps_original_sources_and_ledger(budget):
    env = budget
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == env.context.job_id)
            .values(
                state="failed",
                retryable=True,
                lease_token=None,
                lease_until=None,
            )
        )
    path = f"/api/jobs/{env.context.job_id}/resume"
    first = env.client.post(path)
    assert first.status_code == 202, first.text
    again = env.client.post(path)
    assert first.json()["job_id"] == again.json()["job_id"]
    new = env.repo.get_job(first.json()["job_id"], internal=True)
    old = env.repo.get_job(env.context.job_id, internal=True)
    assert new["payload"]["sources"] == old["payload"]["sources"]
    other, _ = login(env, "b")
    assert other.post(path).status_code == 404


def test_resume_rejects_changed_source_and_nonretryable_work(budget):
    env = budget
    path = f"/api/jobs/{env.context.job_id}/resume"
    assert env.client.post(path).status_code == 409
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == env.context.job_id)
            .values(
                state="failed",
                retryable=True,
                lease_token=None,
            )
        )
        c.execute(db.videos.update().values(generation=99))
    assert env.client.post(path).status_code == 409


def test_provider_retry_time_and_quota_full_resume_are_distinct(budget):
    import time

    env = budget
    with env.db.write() as c:
        c.execute(
            db.v2["circuits"]
            .insert()
            .values(
                key="fixture-project:shared",
                failures=1,
                blocked_until=time.time() + 120,
                reason="provider_rate_limited",
                time_source="provider",
            )
        )
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == env.context.job_id)
            .values(
                state="failed",
                retryable=True,
                lease_token=None,
            )
        )
    data = env.client.get("/api/quota").json()
    blocker = data["pools"][0]["blockers"][0]
    assert blocker["reason"] == "provider_rate_limited"
    assert blocker["time_source"] == "provider" and "retry_at" in blocker
    response = env.client.post(f"/api/jobs/{env.context.job_id}/resume")
    assert response.status_code == 409 and response.json()["error"]["code"] == "quota_unavailable"
