"""Two-member acceptance fixtures for the server-injected authority contract."""

import asyncio
import time
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B, BranchModel, Context
from youtube_backend.errors import AppError, LeaseLost
from youtube_backend.schemas import Source

from youtube_agent.authorization import BackendMemberAuthority, MemberAgentService
from youtube_agent.integration import create_member_adapters


class Authority:
    def __init__(self):
        self.owners = {"job-a": "a", "job-b": "b"}
        self.grants = {"a": {VIDEO_A}, "b": {VIDEO_A, VIDEO_B}}
        self.suspended = set()
        self.active = set()
        self.checks = 0
        self.budget = {"a": 100, "b": 100}
        self.permits = []

    def open(self, context, sources, kind):
        actor = self.owners[context.job_id]  # Durable job actor, independent of browser cookie.
        if context.request_actor != actor or actor in self.active:
            raise AppError("forbidden", "Owner or quota mismatch", 403, False)
        self.active.add(actor)

        def check():
            self.checks += 1
            if (
                actor in self.suspended
                or context.request_actor != actor
                or not {s.video_id for s in sources}.issubset(self.grants[actor])
            ):
                raise PermissionError("Not authorized")

        def consume():
            if self.budget[actor] <= 0:
                raise AppError(
                    "member_budget_exhausted", "Member operation limit reached", 429, False
                )
            self.budget[actor] -= 1

        permit = SimpleNamespace(
            actor_id=actor, check=check, consume=consume, close=lambda: self.active.remove(actor)
        )
        self.permits.append(permit)
        return permit


def member(unit, actor="a", authority=None):
    unit.ctx.job_id = f"job-{actor}"
    unit.ctx.request_actor = actor
    authority = authority or Authority()
    unit.service.model = BranchModel()
    return MemberAgentService(unit.service, authority), authority


async def test_missing_authority_fails_before_model_configuration():
    with pytest.raises(AppError, match="Backend member authority required"):
        await create_member_adapters(settings=None, repository=object())


async def test_foreign_video_denied_before_any_provider_call(unit):
    service, authority = member(unit)
    sources = [Source(video_id=VIDEO_B, generation=1, transcript_version="v1")]
    with pytest.raises(AppError) as exc:
        await service.research(unit.request, sources, unit.ctx)
    assert exc.value.code == "member_access_denied"
    assert not unit.service.model.history and not unit.knowledge.calls
    assert not authority.active


async def test_foreign_job_denied_even_with_admin_label(unit):
    service, authority = member(unit)
    unit.ctx.request_actor = "b"
    unit.ctx.role = "admin"
    with pytest.raises(AppError):
        await service.research(unit.request, unit.sources, unit.ctx)
    assert not authority.active


@pytest.mark.parametrize("boundary", ["search", "read", "inventory", "evidence", "model"])
async def test_revocation_during_await_never_returns_partial(unit, boundary):
    service, authority = member(unit)
    if boundary == "model":
        target, name = unit.service.model, "decide"
    else:
        target, name = unit.knowledge, boundary
    original = getattr(target, name)

    async def revoke(*args, **kwargs):
        value = await original(*args, **kwargs)
        authority.grants["a"].clear()
        return value

    setattr(target, name, revoke)
    with pytest.raises(AppError) as exc:
        await service.research(unit.request, unit.sources, unit.ctx)
    assert exc.value.code == "member_access_denied"
    assert not authority.active
    assert not any(
        e.tool_name == "run_controller" and e.state in {"partial", "completed"}
        for e in unit.ctx.events
    )


@pytest.mark.parametrize("kind", ["quiz", "flashcards", "study_plan"])
async def test_artifact_generation_account_suspension_discards_output(unit, kind):
    service, authority = member(unit)
    original = unit.service.model.generate

    async def suspend(*args):
        value = await original(*args)
        authority.suspended.add("a")
        return value

    unit.service.model.generate = suspend
    request = {"type": kind, "scope": unit.request["scope"], "days": 7}
    with pytest.raises(AppError) as exc:
        await service.artifact(request, unit.sources, unit.ctx)
    assert exc.value.code == "member_access_denied"
    assert not authority.active


async def test_revocation_for_a_does_not_cancel_b_shared_source(unit):
    authority = Authority()
    authority.grants["a"].clear()
    service, _ = member(unit, "b", authority)
    result = await service.research(unit.request, unit.sources, unit.ctx)
    assert result.state == "completed"
    assert not authority.active


async def test_budget_partial_and_cookie_independent_background_job(unit):
    service, authority = member(unit)
    unit.ctx.cookie_expired = True
    unit.config.agent_max_steps = 1
    result = await service.research(unit.request, unit.sources, unit.ctx)
    assert result.state == "partial" and not result.coverage.complete
    assert not authority.active


@pytest.mark.parametrize("failure", [LeaseLost, asyncio.CancelledError])
async def test_cancellation_releases_slot(unit, failure):
    service, authority = member(unit)

    async def cancel(*args):
        raise failure()

    unit.service.model.decide = cancel
    with pytest.raises(failure):
        await service.research(unit.request, unit.sources, unit.ctx)
    assert not authority.active


async def test_same_member_quota_is_shared_between_service_instances(unit):
    service, authority = member(unit)
    entered, resume = asyncio.Event(), asyncio.Event()
    original = unit.service.model.decide

    async def wait(*args):
        entered.set()
        await resume.wait()
        return await original(*args)

    unit.service.model.decide = wait
    task = asyncio.create_task(service.research(unit.request, unit.sources, unit.ctx))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        other = Context()
        other.job_id, other.request_actor = "job-a", "a"
        second = MemberAgentService(unit.service, authority)
        with pytest.raises(AppError):
            await second.research(unit.request, unit.sources, other)
    finally:
        resume.set()
        await task
    assert not authority.active


async def test_member_operation_quota_prevents_provider_cost(unit):
    service, authority = member(unit)
    authority.budget["a"] = 1  # Inventory is allowed, next model call is refused.
    with pytest.raises(AppError):
        await service.research(unit.request, unit.sources, unit.ctx)
    assert not unit.service.model.history
    assert authority.budget["a"] == 0 and authority.budget["b"] == 100
    assert not authority.active


@pytest.mark.parametrize("change", ["actor", "account_switch"])
async def test_actor_binding_cannot_change_during_model_call(unit, change):
    service, authority = member(unit)
    original = unit.service.model.decide

    async def switch(*args):
        value = await original(*args)
        if change == "actor":
            authority.permits[0].actor_id = "b"
        else:
            unit.ctx.request_actor = "b"
        return value

    unit.service.model.decide = switch
    with pytest.raises(AppError) as exc:
        await service.research(unit.request, unit.sources, unit.ctx)
    assert exc.value.code == "member_access_denied"
    assert not unit.knowledge.calls and not authority.active


async def test_direct_service_composition_uses_backend_authority(unit):
    authority = Authority()
    member(unit, authority=authority)
    unit.ctx.settings = SimpleNamespace(auth_enabled=True)
    unit.ctx.repository = SimpleNamespace(agent_authority=authority)
    authority.grants["a"].clear()
    with pytest.raises(AppError):
        await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert not unit.service.model.history


def test_durable_backend_admission_and_operation_budget(unit, monkeypatch):
    from youtube_agent import authorization

    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    jobs = sa.Table(
        "jobs",
        metadata,
        sa.Column("job_id", sa.String, primary_key=True),
        sa.Column("owner_id", sa.String),
        sa.Column("kind", sa.String),
        sa.Column("state", sa.String),
        sa.Column("created_at", sa.Integer),
        sa.Column("lease_token", sa.String, default="lease"),
        sa.Column("lease_until", sa.Float, default=lambda: time.time() + 120),
    )
    metadata.create_all(engine)
    monkeypatch.setattr(authorization.db, "jobs", jobs)
    with engine.begin() as connection:
        connection.execute(
            jobs.insert(),
            [
                dict(job_id="a1", owner_id="a", kind="research", state="running", created_at=1),
                dict(job_id="a2", owner_id="a", kind="research", state="running", created_at=2),
                dict(job_id="b1", owner_id="b", kind="research", state="running", created_at=3),
            ],
        )
    ctx = unit.ctx
    ctx.job_id, ctx.lease_token, ctx.user_id = "a1", "lease", "a"
    ctx.settings = SimpleNamespace(auth_enabled=True)
    ctx.authorize_sources = lambda sources: tuple(sources)

    def execution(job_id, token):
        with engine.connect() as connection:
            return (
                connection.execute(sa.select(jobs).where(jobs.c.job_id == job_id)).mappings().one()
            )

    ctx.repository = SimpleNamespace(
        db=SimpleNamespace(read=engine.connect, write=engine.begin), check_execution=execution
    )
    authority = BackendMemberAuthority(max_concurrent=1, max_operations=1)
    try:
        permit = authority.open(ctx, tuple(unit.sources), "research")
        ctx.job_id = "a2"
        with pytest.raises(AppError) as exc:
            BackendMemberAuthority(max_concurrent=1).open(ctx, tuple(unit.sources), "research")
        assert exc.value.code == "member_concurrency_limit"
        ctx.job_id = "a1"
        permit.consume()
        with pytest.raises(AppError) as exc:
            permit.consume()
        assert exc.value.code == "member_budget_exhausted"
        permit.close()
        with pytest.raises(AppError) as exc:
            authority.open(ctx, tuple(unit.sources), "research")
        assert exc.value.code == "member_execution_duplicate"
        ctx.job_id, ctx.user_id = "b1", "b"
        authority.open(ctx, tuple(unit.sources), "research").consume()
        # Simulate a crashed worker: 02 replaces its lease without calling permit.close().
        with engine.begin() as connection:
            connection.execute(jobs.update().where(jobs.c.job_id == "b1").values(lease_token="new"))
        ctx.lease_token = "new"
        recovered = BackendMemberAuthority(max_concurrent=1, max_operations=1).open(
            ctx, tuple(unit.sources), "research"
        )
        recovered.consume()
        recovered.close()
    finally:
        engine.dispose()
