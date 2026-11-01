import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import sqlalchemy as sa
from test_free_tier import budget as budget
from test_identity import identity as identity

from youtube_backend import database as db
from youtube_backend.errors import AppError
from youtube_backend.local_inference import LocalInference, execution_identity, private_url
from youtube_backend.quota import daily_window

DIGEST = "a" * 64


def local(env):
    env.settings.generation_provider = "ollama"
    env.settings.local_model = "fixture:tiny"
    env.settings.local_model_digest = DIGEST
    with env.db.write() as c:
        job = env.repo._owned(c, env.context.job_id, env.context.lease_token)
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == job["job_id"])
            .values(payload=dict(job["payload"], execution=execution_identity(env.settings)))
        )


def request(key="one"):
    return dict(
        model="fixture:tiny",
        digest=DIGEST,
        operation="chat",
        payload={"messages": [{"role": "user", "content": "ข้อมูลไทย"}]},
        call_key=key,
    )


@pytest.mark.parametrize("date,hours", [("2026-03-08", 23), ("2026-11-01", 25), ("2026-06-01", 24)])
def test_pacific_calendar_handles_dst(date, hours):
    now = (
        datetime.fromisoformat(date + "T12:00:00")
        .replace(tzinfo=ZoneInfo("America/Los_Angeles"))
        .timestamp()
    )
    start, end = daily_window(now)
    assert start <= now < end
    assert end - start == hours * 3600


@pytest.mark.parametrize(
    "url",
    [
        "https://ollama.com",
        "http://8.8.8.8:11434",
        "http://user:pass@localhost",
        "http://localhost/api",
        "http://localhost?redirect=remote",
    ],
)
def test_local_transport_rejects_remote_and_ambiguous_urls(url):
    with pytest.raises(AppError):
        private_url(url)


async def test_local_works_without_gemini_policy_and_never_repeats_call_key(budget):
    env = budget
    local(env)
    env.policy_file.unlink()
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "fixture:tiny", "digest": DIGEST}]}
            )
        body = json.loads(req.content)
        assert body["stream"] is False
        assert body["options"]["num_ctx"] == 4096
        return httpx.Response(
            200,
            json={
                "model": "fixture:tiny",
                "done": True,
                "done_reason": "stop",
                "message": {"content": "fixture only"},
            },
        )

    service = LocalInference(env.context, transport=httpx.MockTransport(handler))
    assert (await service.call(**request()))["done"]
    with pytest.raises(AppError) as caught:
        await service.call(**request())
    assert caught.value.code == "reservation_used"
    assert seen == ["/api/tags", "/api/chat", "/api/tags"]
    with env.db.read() as c:
        rows = list(c.execute(sa.select(db.v2["reservations"])).mappings())
    assert len(rows) == 1 and rows[0]["project"] == "local:ollama"
    assert rows[0]["state"] == "completed"


async def test_missing_model_sends_no_prompt_and_has_no_fallback(budget):
    local(budget)
    seen = []

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200, json={"models": []})

    with pytest.raises(AppError) as caught:
        await LocalInference(budget.context, transport=httpx.MockTransport(handler)).call(
            **request()
        )
    assert caught.value.code == "local_model_changed"
    assert seen == ["/api/tags"]


async def test_local_cancellation_keeps_uncertain_ledger_and_blocks_parallel_calls(budget):
    local(budget)
    entered = asyncio.Event()

    async def handler(req):
        if req.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "fixture:tiny", "digest": DIGEST}]}
            )
        entered.set()
        await asyncio.Event().wait()

    service = LocalInference(budget.context, transport=httpx.MockTransport(handler))
    task = asyncio.create_task(service.call(**request()))
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises(AppError) as caught:
        await service.call(**request("parallel"))
    assert caught.value.code == "local_busy"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with budget.db.read() as c:
        assert c.scalar(sa.select(db.v2["reservations"].c.state)) == "uncertain"


async def test_provider_change_rejects_old_job_before_network(budget):
    budget.settings.generation_provider = "ollama"
    budget.settings.local_model = "fixture:tiny"
    budget.settings.local_model_digest = DIGEST
    with pytest.raises(AppError) as caught:
        await LocalInference(budget.context).call(**request())
    assert caught.value.code == "execution_changed"


def test_previous_provider_day_does_not_block_new_day_and_ledger_is_retained(budget):
    from test_free_tier import reserve

    env = budget
    env.policy["pools"]["shared"]["rpd"] = 1
    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    permit = reserve(env)
    start, _ = daily_window(env.broker.clock())
    with env.db.write() as c:
        c.execute(db.v2["reservations"].update().values(state="completed", created_at=start - 1))
    assert reserve(env, "next-day") != permit
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.v2["reservations"])) == 2


def test_checkpoint_is_private_bounded_and_lease_fenced(budget):
    assert budget.context.checkpoint("result") is None
    budget.context.checkpoint("result", {"answer": "synthetic"})
    assert budget.context.checkpoint("result") == {"answer": "synthetic"}
    with pytest.raises(AppError):
        budget.context.checkpoint("oversize", {"value": "x" * 512_000})
    from youtube_backend.auth import actor_id

    token = actor_id.set(budget.user["user_id"])
    try:
        budget.repo.cancel(budget.context.job_id)
    finally:
        actor_id.reset(token)
    with pytest.raises(AppError):
        budget.context.checkpoint("result")


def test_checkpoint_rejects_changed_provider_even_without_outbound_call(budget):
    budget.context.checkpoint("result", {"answer": "synthetic"})
    budget.settings.generation_provider = "ollama"
    with pytest.raises(AppError) as caught:
        budget.context.checkpoint("result")
    assert caught.value.code == "execution_changed"
