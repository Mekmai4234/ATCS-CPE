"""Explicit, idempotent restart of failed generation work with its frozen sources."""

import sqlalchemy as sa

from . import database as db
from .errors import AppError
from .quota import QuotaBroker
from .quota_status import quota_status
from .repository import ACTIVE, digest, row, uid


def resume(repo, job_id, moderation_token=None):
    old = repo.get_job(job_id)
    if old["kind"] not in {"chat", "analysis", "artifact", "research"}:
        return repo.retry(job_id)
    moderation_event_id = None
    if old["kind"] == "chat":
        if not old["payload"]["request"].get("question"):
            raise AppError("retry_not_allowed", "History has been deleted", 409)
        from .moderation import admit

        moderation_event_id = admit(
            repo, dict(old["payload"]["request"], moderation_token=moderation_token)
        )
    # A committed replacement is returned before checking a now-consumed budget.
    key = digest([old["owner_id"], "explicit-resume", job_id])
    with repo.db.read() as c:
        repo._private(c, old)
        existing = row(c, db.jobs, db.jobs.c.idempotency_key == key)
        if existing:
            return existing
    if old["state"] not in {"failed", "paused"} or not old["retryable"]:
        raise AppError("retry_not_allowed", "Only retryable stopped work can resume", 409)
    state = quota_status(repo)
    _, grant = QuotaBroker(repo).access(
        repo.settings.llm_model,
        "generateContent",
        "agent" if old["kind"] in {"research", "artifact"} else "chat",
    )
    pools = [p for p in state["pools"] if p["bucket"] == grant.bucket]
    if state["status"] == "unverified" or not pools or pools[0]["status"] != "available":
        raise AppError("quota_unavailable", "Local budget or verified policy is not ready", 409)
    with repo.db.write() as c:
        old = row(c, db.jobs, db.jobs.c.job_id == job_id)
        repo._private(c, old)
        existing = row(c, db.jobs, db.jobs.c.idempotency_key == key)
        if existing:
            return existing
        if old["state"] not in {"failed", "paused"} or not old["retryable"]:
            raise AppError("retry_not_allowed", "Job state changed", 409)
        repo._check_sources(c, old["payload"]["sources"], owner=old["owner_id"])
        if old["conversation_id"] and c.scalar(
            sa.select(db.jobs.c.job_id)
            .where(db.jobs.c.conversation_id == old["conversation_id"], db.jobs.c.state.in_(ACTIVE))
            .limit(1)
        ):
            raise AppError("conversation_busy", "Wait for the pending conversation turn", 409)
        job = repo._new_job(
            c,
            old["kind"],
            dict(old["payload"], resumes=job_id, moderation_event_id=moderation_event_id),
            conversation_id=old["conversation_id"],
            idempotency_key=key,
            request_hash=old["request_hash"],
        )
        if old["kind"] == "chat":
            if moderation_event_id:
                c.execute(
                    db.review["events"]
                    .update()
                    .where(db.review["events"].c.event_id == moderation_event_id)
                    .values(job_id=job["job_id"])
                )
            c.execute(
                db.messages.insert().values(
                    message_id=uid(),
                    conversation_id=old["conversation_id"],
                    job_id=job["job_id"],
                    role="user",
                    content=old["payload"]["request"]["question"],
                    scope=old["payload"]["sources"],
                    created_at=repo._message_timestamp(c, old["conversation_id"]),
                )
            )
        return job
