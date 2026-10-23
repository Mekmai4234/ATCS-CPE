"""Account administration exposes identity/state/counts, never private task contents."""

import time
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict

from . import database as db
from .auth import actor_id, public_user
from .errors import AppError


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "admin"] | None = None
    status: Literal["active", "suspended"] | None = None


def require_admin(c):
    user = (
        c.execute(
            sa.select(db.users).where(
                db.users.c.user_id == actor_id.get(), db.users.c.status == "active"
            )
        )
        .mappings()
        .first()
    )
    if not user or user["role"] != "admin":
        raise AppError("admin_required", "Administrator role required", 403)
    return user


def change_member(database, target_id, change):
    with database.write() as c:
        actor = require_admin(c)
        target = (
            c.execute(sa.select(db.users).where(db.users.c.user_id == target_id)).mappings().first()
        )
        if not target:
            raise AppError("not_found", "Member not found", 404)
        values = change.model_dump(exclude_none=True)
        if not values:
            raise AppError("invalid_update", "Provide role or status", 422)
        role, status = values.get("role", target["role"]), values.get("status", target["status"])
        if (
            target["role"] == "admin"
            and target["status"] == "active"
            and (role != "admin" or status != "active")
        ):
            count = c.scalar(
                sa.select(sa.func.count())
                .select_from(db.users)
                .where(db.users.c.role == "admin", db.users.c.status == "active")
            )
            if count <= 1:
                raise AppError("last_admin", "Cannot remove the last active administrator", 409)
        c.execute(
            db.users.update()
            .where(db.users.c.user_id == target_id)
            .values(**values, updated_at=time.time())
        )
        c.execute(
            db.sessions.update().where(db.sessions.c.user_id == target_id).values(revoked=True)
        )
        if status == "suspended":
            c.execute(
                db.jobs.update()
                .where(
                    db.jobs.c.owner_id == target_id,
                    db.jobs.c.state == "queued",
                    db.jobs.c.kind != "delete",
                )
                .values(
                    state="cancelled",
                    stage="cancelled",
                    cancel_requested=True,
                    error_code="account_suspended",
                )
            )
        c.execute(
            db.admin_audit.insert().values(
                actor_id=actor["user_id"],
                target_id=target_id,
                action="member_update",
                data={
                    "before": {"role": target["role"], "status": target["status"]},
                    "after": {"role": role, "status": status},
                },
                created_at=time.time(),
            )
        )
        return public_user({**target, **values})
