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
    seen = {old["job_id"]}
    for _ in range(100):
        if not existing:
            return None
        repo._private(c, existing)
        if existing["job_id"] in seen:
            raise AppError("replacement_cycle", "Invalid replacement chain", 409)
        seen.add(existing["job_id"])
        following = repo._replay_job(
            c,
            digest([existing["owner_id"], "explicit-resume", existing["job_id"]]),
            request_digest(existing["payload"]["request"]),
        )
        if not following:
            return existing
        if following["payload"]["sources"] != old["payload"]["sources"]:
            raise AppError("idempotency_conflict", "Replacement sources changed", 409)
        existing = following
    raise AppError("replacement_chain_limit", "Replacement chain is too long", 409)


def resume(repo, job_id, moderation_token=None):
    old = repo.get_job(job_id)
    if old["kind"] not in {"chat", "analysis", "artifact", "research", "quiz_grade"}:
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
    from .local_inference import execution_identity

    execution = old["payload"].get("execution")
    if execution and execution != execution_identity(repo.settings):
        raise AppError("execution_changed", "Provider configuration changed; create new work", 409)
    if (execution or {}).get("provider") == "ollama":
        state = None  # Local capacity is admitted atomically by the local execution broker.
    else:
        state = quota_status(repo)
    if state is not None:
        _require_gemini_budget(repo, old, state)
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
        if old["state"] == "paused":
            import time

            c.execute(
                db.jobs.update()
                .where(db.jobs.c.job_id == old["job_id"])
                .values(
                    state="cancelled",
                    stage="cancelled",
                    error_code="resumed",
                    updated_at=time.time(),
                )
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


def _require_gemini_budget(repo, old, state):
    _, grant = QuotaBroker(repo).access(
        repo.settings.llm_model,
        "generateContent",
        "agent" if old["kind"] in {"research", "artifact", "quiz_grade"} else "chat",
    )
    pools = [p for p in state["pools"] if p["bucket"] == grant.bucket]
    if state["status"] == "unverified" or not pools or pools[0]["status"] != "available":
        raise AppError("quota_unavailable", "Local budget or verified policy is not ready", 409)
