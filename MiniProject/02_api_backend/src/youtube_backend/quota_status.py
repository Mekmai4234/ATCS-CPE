"""Read-only local accounting. Never a provider balance or an admission grant."""

import time
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from pydantic import Field

from . import database as db
from .admin import require_admin
from .errors import AppError
from .quota import COUNT_TOKENS_RPM, Limits, QuotaBroker, daily_window
from .repository import iso
from .schemas import Schema
from .workspace import worker_status


class QuotaBlocker(Schema):
    reason: str
    time_source: Literal["estimate", "provider"]
    estimated_retry_at: datetime | None = None
    retry_at: datetime | None = None


class QuotaUsage(Schema):
    requests_provider_day: int = Field(default=0, ge=0)
    requests_24h: int = Field(ge=0)
    requests_60s: int = Field(ge=0)
    tokens_60s: int = Field(ge=0)


class QuotaPool(Schema):
    daily_reset_at: datetime | None = None
    daily_timezone: str = "America/Los_Angeles"
    remaining_requests_provider_day: int | None = Field(default=None, ge=0)
    bucket: str
    status: Literal["waiting", "available"]
    usage: QuotaUsage
    blockers: list[QuotaBlocker]
    limits: Limits | None = None
    remaining_requests_24h: int | None = Field(default=None, ge=0)


class QuotaStatus(Schema):
    accounting_source: Literal["local_ledger"]
    provider_balance_verified: Literal[False]
    scope: Literal["member", "project"]
    observed_at: datetime
    worker: dict
    pools: list[QuotaPool]
    admission_guaranteed: Literal[False]
    status: Literal["waiting", "available", "unverified"]
    reason: str | None = None


def quota_status(repo, *, admin=False, clock=time.time):
    now = clock()
    day_start, day_end = daily_window(now)
    with repo.db.read() as c:
        owner = repo._actor(c)
        if owner is None:
            raise AppError("authentication_required", "Member session required", 401)
        if admin:
            require_admin(c)
    result = dict(
        accounting_source="local_ledger",
        provider_balance_verified=False,
        scope="project" if admin else "member",
        observed_at=iso(now),
        worker=worker_status(repo.settings),
        pools=[],
        admission_guaranteed=False,
    )
    broker = QuotaBroker(repo, clock=clock)
    try:
        policy = broker.policy()
    except AppError as exc:
        return dict(result, status="unverified", reason=exc.code)
    reservations = db.v2["reservations"]
    with repo.db.read() as c:
        # Revalidate identity in the transaction that reads private accounting.
        repo._actor(c)
        if admin:
            require_admin(c)
        rows = [
            dict(r)
            for r in c.execute(
                sa.select(reservations).where(
                    reservations.c.project == policy.project_ref,
                    sa.or_(
                        reservations.c.created_at >= min(day_start, now - 86400),
                        sa.and_(
                            reservations.c.state.in_(["held", "sent"]),
                            reservations.c.expires_at > now,
                        ),
                    ),
                    reservations.c.state != "cancelled",
                )
            ).mappings()
            if r["state"] != "held" or r["expires_at"] > now
        ]
        circuits = {r["key"]: dict(r) for r in c.execute(sa.select(db.v2["circuits"])).mappings()}
        pinned = c.scalar(
            sa.select(db.v2["policies"].c.digest).where(
                db.v2["policies"].c.project == policy.project_ref
            )
        )
    if pinned and pinned != broker.fingerprint(policy):
        return dict(result, status="unverified", reason="quota_policy_mismatch")
    for name, limits in policy.pools.items():
        pool = [r for r in rows if r["bucket"] == name and r["endpoint"] != "countTokens"]
        minute = [r for r in pool if r["created_at"] > now - 60]
        daily = [r for r in pool if r["created_at"] >= day_start or r["state"] == "held"]
        own_minute = [r for r in minute if r["owner_id"] == owner]
        active = [r for r in rows if r["state"] in {"held", "sent"} and r["expires_at"] > now]
        blockers = []

        def block(reason, when, source="estimate", blockers=blockers):
            blockers.append(
                dict(
                    reason=reason,
                    time_source=source,
                    **{"retry_at" if source == "provider" else "estimated_retry_at": iso(when)},
                )
            )

        if len(daily) >= limits.rpd:
            block("local_daily_limit", day_end)
        if len(minute) >= limits.rpm:
            block(
                "local_request_limit",
                sorted(r["created_at"] for r in minute)[len(minute) - limits.rpm] + 60,
            )
        if sum(r["tokens"] for r in minute) >= limits.tpm:
            block("local_token_limit", max(r["created_at"] for r in minute) + 60)
        if len(own_minute) >= limits.user_rpm:
            block(
                "member_request_limit",
                sorted(r["created_at"] for r in own_minute)[len(own_minute) - limits.user_rpm] + 60,
            )
        if (
            len(active) >= repo.settings.gemini_max_concurrent
            or sum(r["owner_id"] == owner for r in active) >= repo.settings.gemini_user_concurrent
        ):
            block("local_concurrency_limit", max(r["expires_at"] for r in active))
        counting = [
            r for r in rows if r["endpoint"] == "countTokens" and r["created_at"] > now - 60
        ]
        if len(counting) >= COUNT_TOKENS_RPM:
            block("local_counting_limit", max(r["created_at"] for r in counting) + 60)
        own_counting = [r for r in counting if r["owner_id"] == owner]
        counting_cap = min(limits.user_rpm, COUNT_TOKENS_RPM)
        if len(own_counting) >= counting_cap:
            block(
                "member_counting_limit",
                sorted(r["created_at"] for r in own_counting)[len(own_counting) - counting_cap]
                + 60,
            )
        circuit = circuits.get(f"{policy.project_ref}:{name}")
        if circuit and circuit["blocked_until"] > now:
            block(circuit["reason"], circuit["blocked_until"], circuit["time_source"])
        visible = pool if admin else [r for r in pool if r["owner_id"] == owner]
        item = dict(
            bucket=name,
            daily_reset_at=iso(day_end),
            status="waiting" if blockers else "available",
            usage=dict(
                requests_24h=sum(r["created_at"] > now - 86400 for r in visible),
                requests_provider_day=sum(
                    r["created_at"] >= day_start or r["state"] == "held" for r in visible
                ),
                requests_60s=sum(r["created_at"] > now - 60 for r in visible),
                tokens_60s=sum(r["tokens"] for r in visible if r["created_at"] > now - 60),
            ),
            blockers=blockers,
        )
        if admin:
            item["limits"] = limits.model_dump()
            item["remaining_requests_24h"] = max(
                0, limits.rpd - sum(r["created_at"] > now - 86400 for r in pool)
            )
            item["remaining_requests_provider_day"] = max(0, limits.rpd - len(daily))
        result["pools"].append(item)
    return dict(
        result,
        status="waiting" if any(p["blockers"] for p in result["pools"]) else "available",
        reason=None,
    )
