"""Member recovery and cross-process worker readiness, with no credential storage."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from . import database as db
from .errors import AppError


def heartbeat_path(settings):
    database_path = Path(make_url(settings.database_url).database).resolve()
    return database_path.with_name(database_path.name + ".worker.json")


def beat(settings):
    target = heartbeat_path(settings)
    temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps({"seen_at": time.time()}), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def worker_status(settings):
    threshold = max(30, settings.worker_poll_seconds * 3, settings.job_lease_seconds)
    try:
        seen = float(json.loads(heartbeat_path(settings).read_text(encoding="utf-8"))["seen_at"])
        age = time.time() - seen
        if not -5 <= age <= threshold:
            return {"status": "stale", "ready": False}
        return {"status": "ready", "ready": True}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unknown", "ready": False}


def member_jobs(repo, *, limit=50, offset=0, include_completed=False):
    if not repo.settings.auth_enabled:
        raise AppError("authentication_required", "Member session required", 401)
    with repo.db.read() as connection:
        owner = repo._actor(connection)
        conditions = [db.jobs.c.owner_id == owner]
        if not include_completed:
            conditions.append(db.jobs.c.state.in_(["queued", "running", "paused"]))
        statement = (
            sa.select(db.jobs)
            .where(*conditions)
            .order_by(db.jobs.c.created_at.desc(), db.jobs.c.job_id.desc())
        )
        records = [
            dict(record)
            for record in connection.execute(statement.limit(limit).offset(offset)).mappings()
        ]
        total = connection.scalar(
            sa.select(sa.func.count()).select_from(db.jobs).where(*conditions)
        )
    return dict(
        items=[
            dict(
                repo.public_job(job),
                request=job["payload"].get("request", {}),
                sources=job["payload"].get("sources", []),
            )
            for job in records
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
