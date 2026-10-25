"""Durable project budgets use test attestations, never an actual Google account."""

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from test_identity import VIDEO, login, ready
from test_identity import identity as identity

from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.media import MediaStore
from youtube_backend.provider_errors import provider_error, retry_seconds
from youtube_backend.quota import ProviderReply, QuotaBroker
from youtube_backend.runtime import ManagedAdapters


def context_for(env, user, kind="enrich"):
    token = actor_id.set(user["user_id"])
    try:
        queued = (
            env.repo.enqueue("chat", {"question": "fixture", "scope": {"video_ids": [VIDEO]}})
            if kind == "chat"
            else MediaStore(env.repo).enqueue(VIDEO)
        )
    finally:
        actor_id.reset(token)
    job = env.repo.claim(queued["job_id"])
    assert job
    return ExecutionContext(
        env.repo, job["job_id"], job["lease_token"], job["deadline_at"], env.settings
    )


@pytest.fixture
def budget(identity, tmp_path):
    client, user = login(identity, "a")
    ready(identity, client)
    identity.settings.gemini_api_key = SecretStr("fixture-free-project-key")
    now = datetime.now(UTC)
    policy = dict(
        tier="free",
        project_ref="fixture-project",
        verified_by="fixture-operator",
        evidence_ref="fixture-not-a-real-billing-check",
        key_sha256=hashlib.sha256(b"fixture-free-project-key").hexdigest(),
        verified_at=(now - timedelta(minutes=1)).isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat(),
        pools={"shared": dict(rpm=10, tpm=1000, rpd=20, user_rpm=10)},
        models=[
            dict(
                model=identity.settings.llm_model,
                bucket="shared",
                endpoints=["generateContent", "countTokens", "embedContent"],
                returned_models=[identity.settings.llm_model],
                roles=["chat", "vision", "embedding", "agent"],
                image_capable=True,
            )
        ],
    )
    file = tmp_path / "operator-policy.json"
    file.write_text(json.dumps(policy), encoding="utf-8")
    identity.settings.gemini_free_policy_file = str(file)
    identity.policy, identity.policy_file = policy, file
    identity.client, identity.user = client, user
    identity.context = context_for(identity, user, kind="chat")
    identity.broker = QuotaBroker(identity.repo)
    return identity


def reserve(env, key="call-1", **extra):
    return env.broker.reserve(
        env.context,
        model=env.settings.llm_model,
        endpoint="generateContent",
        input_tokens=100,
        call_key=key,
        **extra,
    )


def test_gate_rejects_unknown_expired_changed_key_and_paid_policy(budget):
    env = budget
    for change in (
        {"tier": "paid"},
        {"key_sha256": "0" * 64},
        {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
    ):
        env.policy_file.write_text(json.dumps(dict(env.policy, **change)), encoding="utf-8")
        with pytest.raises(AppError, match="verification"):
            reserve(env)
    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    with pytest.raises(AppError) as denied:
        env.broker.access("unverified-paid-fallback", "generateContent")
    assert denied.value.code == "free_model_unverified"
    with env.db.read() as c:
        assert not list(c.execute(sa.select(db.v2["reservations"])))


def test_model_grants_are_role_specific_and_vision_is_not_implicitly_enabled(budget):
    env = budget
    env.policy["models"][0].update(roles=["chat"], image_capable=False)
    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    env.broker.access(env.settings.llm_model, "generateContent", "chat")
    with pytest.raises(AppError) as denied:
        env.broker.access(env.settings.llm_model, "generateContent", "vision")
    assert denied.value.code == "free_model_unverified"
    with pytest.raises(AppError) as escalation:
        env.broker.reserve(
            env.context,
            model=env.settings.llm_model,
            endpoint="generateContent",
            input_tokens=10,
            call_key="not-an-agent",
            role="agent",
        )
    assert escalation.value.code == "budget_role_denied"


def test_cross_process_reservations_cannot_spend_same_project_slot(budget):
    env = budget
    other, user = login(env, "b")
    ready(env, other)
    second = context_for(env, user)
    program = """
import json,sys
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.repository import Repository
from youtube_backend.integrations import ExecutionContext
from youtube_backend.quota import QuotaBroker
from youtube_backend.errors import AppError
s=Settings(_env_file=None,**json.loads(sys.argv[1]))
d=Database(s.database_url); r=Repository(d,s)
c=ExecutionContext(r,*json.loads(sys.argv[2]),s)
try:
    token=QuotaBroker(r).reserve(c,model=s.llm_model,endpoint="generateContent",input_tokens=100,call_key="parallel")
    print(json.dumps({"reserved":token}))
except AppError as e:
    print(json.dumps({"error":e.code}))
finally:
    d.close()
"""
    values = env.settings.model_dump(mode="json")
    values["gemini_api_key"] = env.settings.gemini_api_key.get_secret_value()

    # Fixture key only; real keys are never passed through argv by delivery code.
    def child(context):
        binding = [context.job_id, context.lease_token, context.deadline_at]
        result = subprocess.run(
            [sys.executable, "-c", program, json.dumps(values), json.dumps(binding)],
            capture_output=True,
            text=True,
            timeout=25,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(child, [env.context, second]))
    assert sum("reserved" in result for result in results) == 1
    assert [r["error"] for r in results if "error" in r] == ["quota_wait"]


def test_dispatch_once_reconcile_input_usage_and_conservative_uncertain_accounting(budget):
    env = budget
    permit = reserve(env)
    env.broker.dispatch(env.context, permit)
    with pytest.raises(AppError) as reused:
        env.broker.dispatch(env.context, permit)
    assert reused.value.code == "reservation_used"
    with pytest.raises(AppError):
        reserve(env)
    env.broker.settle(permit, reply=ProviderReply("answer", 25, env.settings.llm_model))
    permit = reserve(env, "timeout")
    env.broker.dispatch(env.context, permit)
    with pytest.raises(AppError):
        env.broker.settle(permit, unsent=True)
    env.broker.settle(permit)
    with env.db.read() as c:
        rows = c.execute(sa.select(db.v2["reservations"])).mappings().all()
    assert [(r["state"], r["tokens"]) for r in rows] == [("completed", 25), ("uncertain", 100)]


@pytest.mark.parametrize("dimension", ["rpm", "tpm", "rpd", "user_rpm"])
def test_configured_project_and_member_limits_are_shared_by_endpoints(budget, dimension):
    env = budget
    env.policy["pools"]["shared"][dimension] = 100 if dimension == "tpm" else 1
    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    permit = reserve(env)
    env.broker.dispatch(env.context, permit)
    env.broker.settle(permit)  # Unknown outcome retains estimated charges.
    with pytest.raises(AppError) as wait:
        env.broker.reserve(
            env.context,
            model=env.settings.llm_model,
            endpoint="countTokens",
            input_tokens=1,
            call_key="count-also-consumes-budget",
        )
    assert wait.value.code == "quota_wait"
    assert wait.value.retry_time_source == "estimate"


def test_held_cancellation_refunds_but_inconsistent_workers_fail_closed(budget):
    env = budget
    permit = reserve(env)
    env.broker.settle(permit, unsent=True)
    held = reserve(env, "next")
    env.policy["pools"]["shared"]["rpm"] = 11
    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    with pytest.raises(AppError) as mismatch:
        reserve(env, "different-config")
    assert mismatch.value.code == "quota_policy_mismatch"
    env.broker.install_policy()
    with pytest.raises(AppError) as stale:
        env.broker.dispatch(env.context, held)
    assert stale.value.code == "quota_policy_mismatch"
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.v2["reservations"])) == 2


def test_503_is_not_quota_and_retry_metadata_is_bounded(budget):
    env = budget
    assert provider_error(503).code == "provider_unavailable"
    assert provider_error(429).code == "provider_rate_limited"
    assert not provider_error(403).retryable
    for value in ("nan", "inf", "-10", "Bearer secret", "999999999"):
        assert retry_seconds(value) is None
    permit = reserve(env)
    env.broker.dispatch(env.context, permit)
    env.broker.settle(permit, error=provider_error(503, retry_after="120"))
    with pytest.raises(AppError) as circuit:
        reserve(env, "no-rapid-retry")
    assert circuit.value.code == "provider_unavailable" and circuit.value.status_code == 503
    assert provider_error(429, retry_after="60").retry_time_source == "provider"
    assert provider_error(429).retry_time_source is None


def test_returned_model_drift_blocks_further_calls(budget):
    env = budget
    env.policy["project_ref"] = "fixture_project"
    env.policy_file.write_text(json.dumps(env.policy), encoding="utf-8")
    permit = reserve(env)
    env.broker.dispatch(env.context, permit)
    with pytest.raises(AppError) as changed:
        env.broker.settle(permit, reply=ProviderReply("ignored", 30, "unknown-paid-model"))
    assert changed.value.code == "returned_model_unverified"
    with pytest.raises(AppError) as blocked:
        reserve(env, "next")
    assert blocked.value.code == "returned_model_unverified"
    with env.db.write() as c:
        c.execute(
            db.v2["circuits"]
            .insert()
            .values(
                key="fixtureXproject:shared",
                failures=1,
                blocked_until=env.broker.clock() + 60,
                reason="returned_model_unverified",
                time_source="estimate",
            )
        )
    env.broker.install_policy(review_model_changes=True)
    with env.db.read() as c:
        assert (
            c.scalar(
                sa.select(db.v2["circuits"].c.key).where(
                    db.v2["circuits"].c.key == "fixtureXproject:shared"
                )
            )
            == "fixtureXproject:shared"
        )
    assert reserve(env, "operator-reviewed")


def test_waiters_prioritize_chat_and_preserve_fifo_between_members(budget):
    env = budget
    other, user = login(env, "b")
    ready(env, other)
    interactive = context_for(env, user, kind="chat")
    background = context_for(env, user)
    active = reserve(env, "held-by-a")
    with pytest.raises(AppError):
        env.broker.reserve(
            interactive,
            model=env.settings.llm_model,
            endpoint="generateContent",
            input_tokens=10,
            call_key="chat-wait",
        )
    env.broker.settle(active, unsent=True)
    with pytest.raises(AppError):
        env.broker.reserve(
            background,
            model=env.settings.llm_model,
            endpoint="generateContent",
            input_tokens=10,
            call_key="background-wait",
        )
    permit = env.broker.reserve(
        interactive,
        model=env.settings.llm_model,
        endpoint="generateContent",
        input_tokens=10,
        call_key="chat-first",
    )
    env.broker.settle(permit, unsent=True)
    assert reserve(env, "next-interactive-a")


async def test_callback_reconciliation_count_request_and_timeout(budget):
    import asyncio

    env = budget

    async def count():
        return ProviderReply(7, 10, None)  # countTokens does not report a returned model.

    response = await env.context.gemini_call(
        count,
        model=env.settings.llm_model,
        endpoint="countTokens",
        input_tokens=100,
        call_key="count-once",
    )
    assert response.value == 7 and response.reservation_id
    env.settings.llm_timeout_seconds = 0.5

    async def slow():
        await asyncio.sleep(1)

    with pytest.raises(AppError) as timeout:
        await env.context.gemini_call(
            slow,
            model=env.settings.llm_model,
            endpoint="generateContent",
            input_tokens=100,
            call_key="bounded-http",
        )
    assert timeout.value.code == "provider_timeout"
    with env.db.read() as c:
        rows = c.execute(sa.select(db.v2["reservations"])).mappings().all()
    assert [r["state"] for r in rows] == ["completed", "uncertain"]


def test_policy_revoked_between_reservation_and_dispatch_cannot_send(budget):
    env = budget
    permit = reserve(env)
    env.policy_file.write_text("{}", encoding="utf-8")
    with pytest.raises(AppError):
        env.broker.dispatch(env.context, permit)
    env.broker.settle(permit, unsent=True)


async def test_vision_publication_and_citation_require_bound_reconciled_call(budget, tmp_path):
    from test_media_v2 import bundle

    from youtube_backend.evidence_v2 import VisualCitationV2

    env = budget
    env.settings.media_asset_dir = str(tmp_path / "images")
    context = context_for(env, env.user)
    store = MediaStore(env.repo)
    visual = bundle()
    visual.frames[0].visual_text = "[VISION FIXTURE] A title card"
    visual.requested_model = visual.returned_model = env.settings.llm_model
    visual.vision_input_hash = hashlib.sha256(b"fixture-vision-input").hexdigest()
    visual.vision_reservation_id = "untrusted-proof"
    with pytest.raises(AppError) as forged:
        store.publish(context, visual)
    assert forged.value.code == "vision_budget_required"

    async def generate():
        return ProviderReply("[VISION FIXTURE] A title card", 100, env.settings.llm_model)

    reply = await context.gemini_call(
        generate,
        model=env.settings.llm_model,
        endpoint="generateContent",
        input_tokens=100,
        call_key="vision-frame-1",
        input_hash=visual.vision_input_hash,
    )
    visual.vision_reservation_id = reply.reservation_id
    result = store.publish(context, visual)
    source = next(s for s in result["snapshots"] if s["kind"] == "visual")
    evidence = env.client.get(f"/api/v2/videos/{VIDEO}/evidence").json()
    record = next(e for e in evidence["evidence"] if e["kind"] == "visual")
    citation = VisualCitationV2(
        source=source,
        frame_id=record["frame_id"],
        asset_id=record["asset_id"],
        start_seconds=record["timestamp_seconds"],
        text=record["text"],
        asset_url=record["asset_url"],
    )
    assert store.verify_citation(context, citation) == citation
    with pytest.raises(AppError) as wrong_frame:
        store.verify_citation(context, citation.model_copy(update={"start_seconds": 9}))
    assert wrong_frame.value.code == "invalid_citation"


async def test_callback_is_never_invoked_without_gate_or_after_revocation(budget):
    env = budget
    calls = []

    async def callback():
        calls.append(True)
        return ProviderReply("ok", 5, env.settings.llm_model)

    env.settings.gemini_free_policy_file = None
    with pytest.raises(AppError):
        await env.context.gemini_call(
            callback,
            model=env.settings.llm_model,
            endpoint="generateContent",
            input_tokens=10,
            call_key="blocked",
        )
    assert not calls
    env.settings.gemini_free_policy_file = str(env.policy_file)
    with env.db.write() as c:
        c.execute(
            db.users.update()
            .where(db.users.c.user_id == env.user["user_id"])
            .values(status="suspended")
        )
    with pytest.raises(AppError):
        await env.context.gemini_call(
            callback,
            model=env.settings.llm_model,
            endpoint="generateContent",
            input_tokens=10,
            call_key="suspended",
        )
    assert not calls


async def test_unmigrated_provider_adapter_is_blocked_while_local_work_is_allowed(budget):
    env = budget
    env.settings.adapter_mode = "custom"
    env.settings.adapter_factory = "test:server-injected"
    runtime = ManagedAdapters(env.settings, env.repo, object())
    # Exercise the gate alone; repository mode identity is independently covered.
    env.settings.gemini_free_policy_file = None
    with pytest.raises(AppError) as unverified:
        runtime.gemini_gate("answer")
    assert unverified.value.code == "free_tier_unverified"
    runtime.gemini_gate("ingest")  # Current caption extraction is local/non-Gemini.
    env.settings.gemini_free_policy_file = str(env.policy_file)
    with pytest.raises(AppError) as missing_contract:
        runtime.gemini_gate("answer")
    assert missing_contract.value.code == "gemini_broker_required"
