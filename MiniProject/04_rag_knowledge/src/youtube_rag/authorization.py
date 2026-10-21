"""Consume 02's durable actor/source contract; never accept identities from prompts."""

import sqlalchemy as sa
from youtube_backend import database as db

from .errors import error
from .models import digest


def authenticated(settings):
    enabled = getattr(settings, "auth_enabled", None)
    if enabled is None and settings.app_env != "test":
        raise error(
            "authorization_unavailable", "Install the account-aware backend contract", status=503
        )
    if not enabled and settings.app_env not in {"development", "test"}:
        raise error("authentication_required", "Authenticated execution is required", status=403)
    if enabled and not all(hasattr(db, name) for name in ("users", "user_videos")):
        raise error(
            "authorization_unavailable", "Account-aware backend schema is required", status=503
        )
    return bool(enabled)


def permission_scope(context, sources, *, operation="read"):
    job = context.repository.check_execution(context.job_id, context.lease_token)
    identity = {"job": job["job_id"], "sources": [s.model_dump() for s in sources]}
    if not authenticated(context.settings):
        return digest({**identity, "actor": "explicit-test-or-development-legacy"})
    owner = job.get("owner_id")
    if not owner:
        raise error("permission_denied", "Execution has no durable account owner", status=403)
    with context.repository.db.read() as connection:
        user = (
            connection.execute(sa.select(db.users).where(db.users.c.user_id == owner))
            .mappings()
            .first()
        )
        if not user or user["status"] != "active":
            raise error(
                "permission_denied", "Account no longer authorizes this execution", status=403
            )
        # Inventory during shared ingestion is a worker publication check, never text access.
        shared_inventory = operation == "inventory" and job["kind"] == "import"
        grants = []
        for source in sources:
            query = sa.select(db.user_videos.c.user_id, db.user_videos.c.created_at).where(
                db.user_videos.c.video_id == source.video_id
            )
            if shared_inventory:
                query = query.join(db.users).where(db.users.c.status == "active")
            else:
                query = query.where(db.user_videos.c.user_id == owner)
            memberships = connection.execute(query.order_by(db.user_videos.c.user_id)).all()
            if not memberships:
                raise error(
                    "permission_denied", "Library no longer authorizes this source", status=403
                )
            grants.append([list(row) for row in memberships])
    return digest(
        {
            **identity,
            "actor": owner,
            "grants": grants,
            "account_revision": user["updated_at"],
            "operation": operation,
            "frozen_sources": job["payload"].get("sources", []),
        }
    )


def readers(connection, video_id, *, except_job=None):
    rows = connection.execute(
        sa.select(db.jobs).where(
            db.jobs.c.state.in_(["queued", "running"]), db.jobs.c.job_id != (except_job or "")
        )
    ).mappings()
    return any(
        row["video_id"] == video_id
        or any(source.get("video_id") == video_id for source in row["payload"].get("sources", []))
        for row in rows
    )


def references(connection, video_id):
    if not hasattr(db, "user_videos"):
        return False
    return bool(
        connection.scalar(
            sa.select(db.user_videos.c.video_id)
            .where(db.user_videos.c.video_id == video_id)
            .limit(1)
        )
    )
