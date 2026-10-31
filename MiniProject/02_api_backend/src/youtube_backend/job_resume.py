"""Explicit, idempotent restart of failed generation work with its frozen sources."""

import sqlalchemy as sa

from . import database as db
from .errors import AppError
from .moderation import request_digest
from .quota import QuotaBroker
from .quota_status import quota_status
from .repository import ACTIVE, digest, row, uid


def _replacement(repo, c, old, key):
    existing = repo._replay_job(c, key, request_digest(old["payload"]["request"]))
    if existing and existing["payload"]["sources"] != old["payload"]["sources"]:
        raise AppError("idempotency_conflict", "Replacement sources differ from original work", 409)
    return existing


def resume(repo, job_id, moderation_token=None):
    old = repo.get_job(job_id)
    if old["kind"] not in {"chat", "analysis", "artifact", "research"}:
        return repo.retry(job_id)
    # A committed replacement is a read, even after ticket/budget expiry.
    key = digest([old["owner_id"], "explicit-resume", job_id])
    with repo.db.read() as c:
        repo._private(c, old)
        existing = _replacement(repo, c, old, key)
        if existing:
            return existing
    if old["state"] not in {"failed", "paused"} or not old["retryable"]:
        raise AppError("retry_not_allowed", "Only retryable stopped work can resume", 409)
    ticket_id = None
    if old["kind"] == "chat":
        if not old["payload"]["request"].get("question"):
            raise AppError("retry_not_allowed", "History has been deleted", 409)
        from .moderation import admit

        ticket_id = admit(repo, dict(old["payload"]["request"], moderation_token=moderation_token))
    original_hash = request_digest(old["payload"]["request"])
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
        existing = _replacement(repo, c, old, key)
        if existing:
            return existing
        if request_digest(old["payload"]["request"]) != original_hash:
            raise AppError("idempotency_conflict", "Original request changed while resuming", 409)
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
            dict(old["payload"], resumes=job_id, moderation_event_id=None),
            conversation_id=old["conversation_id"],
            idempotency_key=key,
            request_hash=original_hash,
        )
        if old["kind"] == "chat":
            if ticket_id:
                from .moderation import bind_admission

                bind_admission(repo, c, job, ticket_id)
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
