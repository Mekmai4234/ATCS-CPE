"""Fail-closed execution bridge. 02 owns identity; 06 meters its execution permits.

The authority is server-injected, never constructed from requests or model arguments.
See MEMBER_AUTHORIZATION.md for the required backend contract.
"""

import time
from typing import Protocol

import sqlalchemy as sa
from youtube_backend import database as db
from youtube_backend.schemas import Source

from .models import error

metadata = sa.MetaData()
permits = sa.Table(
    "agent06_permits",
    metadata,
    sa.Column("job_id", sa.String, primary_key=True),
    sa.Column("lease_token", sa.String, primary_key=True),
    sa.Column("owner_id", sa.String, nullable=False, index=True),
    sa.Column("active", sa.Boolean, nullable=False),
    sa.Column("remaining", sa.Integer, nullable=False),
)


class MemberPermit(Protocol):
    actor_id: str

    def check(self) -> None:
        """Check account, job ownership and current source grants without spending budget."""

    def consume(self) -> None:
        """Atomically spend a shared per-member operation allowance before a bounded call."""

    def close(self) -> None:
        """Release this execution's concurrency reservation, including on failure."""


class MemberAuthority(Protocol):
    def open(self, context, sources: tuple[Source, ...], kind: str) -> MemberPermit:
        """Atomically bind trusted job actor/scope and reserve a per-member run slot."""


class BackendMemberAuthority:
    """Consume 02's account-aware context without creating another identity database.

    A module-owned table in 02's database reserves slots and meters calls atomically.
    Backend BEGIN IMMEDIATE transactions serialize admission across worker processes.
    """

    def __init__(self, *, max_concurrent=2, max_operations=64):
        if max_concurrent < 1 or max_operations < 1:
            raise ValueError("Member limits must be positive")
        self.max_concurrent = max_concurrent
        self.max_operations = max_operations

    def open(self, context, sources, kind):
        if (
            not getattr(context.settings, "auth_enabled", False)
            or "owner_id" not in db.jobs.c
            or not callable(getattr(context, "authorize_sources", None))
        ):
            raise error(
                "member_authority_unavailable", "Account-aware backend required", status=503
            )
        actor = context.user_id
        context.check()
        context.authorize_sources(sources)
        job = context.repository.check_execution(context.job_id, context.lease_token)
        if not actor or job.get("owner_id") != actor or job["kind"] != kind:
            raise error("member_access_denied", "Job binding mismatch", status=403)
        database = context.repository.db
        key = sa.and_(
            permits.c.job_id == context.job_id, permits.c.lease_token == context.lease_token
        )
        with database.write() as connection:
            metadata.create_all(connection)
            live = sa.exists(
                sa.select(db.jobs.c.job_id).where(
                    db.jobs.c.job_id == permits.c.job_id,
                    db.jobs.c.lease_token == permits.c.lease_token,
                    db.jobs.c.state == "running",
                    db.jobs.c.lease_until > time.time(),
                )
            )
            connection.execute(permits.delete().where(~live))
            if connection.scalar(sa.select(permits.c.job_id).where(key)):
                raise error(
                    "member_execution_duplicate", "Execution permit already used", status=409
                )
            count = connection.scalar(
                sa.select(sa.func.count())
                .select_from(permits)
                .where(permits.c.owner_id == actor, permits.c.active.is_(True))
            )
            if count >= self.max_concurrent:
                raise error("member_concurrency_limit", "Member job limit reached", status=429)
            connection.execute(
                permits.insert().values(
                    job_id=context.job_id,
                    lease_token=context.lease_token,
                    owner_id=actor,
                    active=True,
                    remaining=self.max_operations,
                )
            )

        class Permit:
            actor_id = actor

            def check(self):
                context.check()  # 02 checks active account and current library membership.
                context.authorize_sources(sources)
                if context.user_id != actor:
                    raise error("member_access_denied", "Job owner changed", status=403)
                job = context.repository.check_execution(context.job_id, context.lease_token)
                if not actor or job.get("owner_id") != actor or job["kind"] != kind:
                    raise error("member_access_denied", "Job binding mismatch", status=403)
                with database.read() as connection:
                    active = connection.scalar(sa.select(permits.c.active).where(key))
                if active is not True:
                    raise error("member_access_denied", "Execution permit closed", status=403)

            def consume(self):
                self.check()
                with database.write() as connection:
                    changed = connection.execute(
                        permits.update()
                        .where(key, permits.c.active.is_(True), permits.c.remaining > 0)
                        .values(remaining=permits.c.remaining - 1)
                    ).rowcount
                    if changed != 1:
                        raise error(
                            "member_budget_exhausted", "Member tool limit reached", status=429
                        )

            def close(self):
                with database.write() as connection:
                    connection.execute(permits.update().where(key).values(active=False))

        return Permit()


class MemberContext:
    def __init__(self, context, permit, sources):
        self._context = context
        self._permit = permit
        self._actor = permit.actor_id
        self._sources = sources
        self._snapshot = [s.model_dump() for s in sources]
        self._denied = False

    def __getattr__(self, name):
        return getattr(self._context, name)

    def check(self):
        self._context.check()
        if self._denied:
            raise error(
                "member_access_denied", "Member execution is no longer authorized", status=403
            )
        try:
            if (
                not isinstance(self._actor, str)
                or not self._actor
                or self._permit.actor_id != self._actor
                or [s.model_dump() for s in self._sources] != self._snapshot
            ):
                raise ValueError("Execution binding changed")
            self._permit.check()
        except Exception:
            # Latch denial: the controller must never convert an auth failure into partial output.
            self._denied = True
            raise error(
                "member_access_denied", "Member execution is no longer authorized", status=403
            ) from None

    def event(self, event):
        self.check()
        self._context.event(event)

    def before_agent_call(self):
        self.check()
        self._permit.consume()
        self.check()


def member_service(agent, context):
    """Also protect callers such as 05's composition that construct AgentService directly."""
    if isinstance(context, MemberContext):
        return None
    if not getattr(getattr(context, "settings", None), "auth_enabled", False):
        return None
    authority = getattr(context.repository, "agent_authority", None) or BackendMemberAuthority()
    return MemberAgentService(agent, authority)


class MemberAgentService:
    """Wrap the existing bounded controller without changing legacy dependency metadata."""

    def __init__(self, agent, authority: MemberAuthority):
        if authority is None:
            raise error(
                "member_authority_unavailable", "Backend member authority required", status=503
            )
        self.agent = agent
        self.authority = authority

    async def _execute(self, kind, request, sources, context):
        sources = tuple(Source.model_validate(s).model_copy(deep=True) for s in sources)
        permit = self.authority.open(context, sources, kind)
        try:
            guarded = MemberContext(context, permit, sources)
            guarded.check()
            result = await getattr(self.agent, kind)(request, list(sources), guarded)
            guarded.check()
            return result
        finally:
            permit.close()

    async def research(self, request, sources, context):
        return await self._execute("research", request, sources, context)

    async def artifact(self, request, sources, context):
        return await self._execute("artifact", request, sources, context)
