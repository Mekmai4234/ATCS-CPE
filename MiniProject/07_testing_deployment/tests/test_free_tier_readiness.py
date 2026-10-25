"""07's gate tests use synthetic attestations; they never assert a Google tier."""

import hashlib
import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def gate(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module = importlib.import_module("free_tier")
    now = datetime(2026, 10, 25, tzinfo=UTC)
    settings = SimpleNamespace(
        gemini_api_key=SecretStr("synthetic-never-a-real-key"),
        llm_model="fixture-chat",
        embedding_model="fixture-embed",
        embedding_provider="gemini",
        gemini_free_policy_file=str(tmp_path / "policy.json"),
    )
    source = dict(mode="checkout", revision="a" * 40, source_sha256="b" * 64, dirty=False)
    models = {
        role: dict(
            requested_model="fixture-embed" if role == "embedding" else "fixture-chat",
            returned_models=["fixture-embed" if role == "embedding" else "fixture-chat"],
            endpoint="embedContent" if role == "embedding" else "generateContent",
            rpm=2,
            tpm=1000,
            rpd=10,
        )
        for role in ("chat", "vision", "embedding", "agent")
    }
    evidence = dict(
        schema=1,
        tier="free",
        project_ref="synthetic-project",
        reviewed_by="fixture-operator",
        evidence_ref="fixture-only",
        ai_studio_checked=True,
        key_project_match=True,
        model_access_checked=True,
        checked_at=(now - timedelta(minutes=1)).isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
        key_sha256=hashlib.sha256(settings.gemini_api_key.get_secret_value().encode()).hexdigest(),
        revision=source["revision"],
        source_sha256=source["source_sha256"],
        models=models,
        smoke_budget=dict(max_requests=2, max_input_tokens=500),
        checks=dict.fromkeys(module.CHECKS, True),
    )
    policy = SimpleNamespace(
        project_ref=evidence["project_ref"],
        key_sha256=evidence["key_sha256"],
        verified_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        pools={"shared": SimpleNamespace(rpm=2, tpm=1000, rpd=10)},
        models=[
            SimpleNamespace(
                model=g["requested_model"],
                roles=[role],
                endpoints=[g["endpoint"]],
                returned_models=g["returned_models"],
                bucket="shared",
            )
            for role, g in models.items()
        ],
    )
    Path(settings.gemini_free_policy_file).write_text("{}", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "youtube_backend.quota",
        SimpleNamespace(FreePolicy=SimpleNamespace(model_validate_json=lambda _: policy)),
    )
    return SimpleNamespace(
        module=module,
        settings=settings,
        evidence=evidence,
        source=source,
        policy=policy,
        run=lambda e=evidence: module.check(settings, e, source=source, now=now),
    )


def test_gate_accepts_only_matching_review_but_never_claims_google_check(gate):
    result = gate.run()
    assert result["free_tier_release_ready"]
    assert not result["billing_verified_by_tool"] and not result["provider_request_made"]
    assert gate.settings.gemini_api_key.get_secret_value() not in json.dumps(result)


@pytest.mark.parametrize("change", [None, {"tier": "paid"}, {"tier": "unknown"}])
def test_unknown_or_paid_review_cannot_authorize_live(gate, change):
    evidence = None if change is None else dict(gate.evidence, **change)
    assert not gate.run(evidence)["free_tier_release_ready"]


@pytest.mark.parametrize(
    "field", ["ai_studio_checked", "key_project_match", "model_access_checked"]
)
def test_catalog_or_truthy_string_is_not_operator_confirmation(gate, field):
    gate.evidence[field] = "true"
    assert not gate.run()["free_tier_release_ready"]


@pytest.mark.parametrize(
    "change",
    [
        {"key_sha256": "c" * 64},
        {"revision": "d" * 40},
        {"source_sha256": "e" * 64},
        {"expires_at": "2026-10-24T00:00:00+00:00"},
        {"checked_at": "2026-10-26T00:00:00+00:00"},
        {"checked_at": "2026-10-25T00:00:00"},
        {"smoke_budget": {"max_requests": True, "max_input_tokens": 500}},
        {"smoke_budget": {"max_requests": 4, "max_input_tokens": 500}},
        {"smoke_budget": {"max_requests": 2, "max_input_tokens": 4097}},
    ],
)
def test_drift_time_and_unbounded_smoke_are_rejected(gate, change):
    gate.evidence.update(change)
    assert not gate.run()["free_tier_release_ready"]


@pytest.mark.parametrize("role", ["chat", "vision", "embedding", "agent"])
def test_all_roles_need_matching_grant(gate, role):
    gate.evidence["models"][role]["requested_model"] = "paid-fallback"
    assert not gate.run()["free_tier_release_ready"]


def test_incomplete_suite_dirty_source_and_policy_drift_reject(gate):
    gate.evidence["checks"]["shared_broker_all_requests"] = False
    assert not gate.run()["free_tier_release_ready"]
    gate.evidence["checks"]["shared_broker_all_requests"] = True
    gate.source["dirty"] = True
    assert not gate.run()["free_tier_release_ready"]
    gate.source["dirty"] = False
    gate.policy.pools["shared"].rpm = 99
    assert not gate.run()["free_tier_release_ready"]


def test_live_smoke_and_startup_refuse_before_network_or_process(gate, monkeypatch):
    live = importlib.import_module("live_smoke")
    preflight = importlib.import_module("preflight")
    monkeypatch.setattr(live, "request", lambda *a: pytest.fail("Unexpected request"))
    monkeypatch.setattr(preflight, "resolve", lambda *a: gate.settings)
    monkeypatch.setattr(preflight, "inspect_settings", lambda *a: {})
    monkeypatch.setattr(
        preflight, "check_pair", lambda *a: pytest.fail("Must reject before state/startup")
    )
    monkeypatch.setattr(
        sys, "argv", ["smoke", "--allow-live", "--url", "fixture", "--question", "fixture"]
    )
    with pytest.raises(SystemExit) as rejected:
        live.main()
    assert rejected.value.code == 2
    monkeypatch.setattr(sys, "argv", ["preflight", "--run", "worker"])
    with pytest.raises(SystemExit) as rejected:
        preflight.main()
    assert rejected.value.code == 1


def test_even_accepted_review_does_not_enable_unbounded_legacy_smoke(gate, monkeypatch):
    live = importlib.import_module("live_smoke")
    preflight = importlib.import_module("preflight")
    monkeypatch.setattr(preflight, "resolve", lambda *a: gate.settings)
    monkeypatch.setattr(gate.module, "require", lambda *a: {"free_tier_release_ready": True})
    monkeypatch.setattr(live, "request", lambda *a: pytest.fail("Unexpected provider/API call"))
    monkeypatch.setattr(
        sys, "argv", ["smoke", "--allow-live", "--url", "fixture", "--question", "fixture"]
    )
    with pytest.raises(SystemExit) as rejected:
        live.main()
    assert rejected.value.code == 2


def test_offline_drill_rejects_real_or_alternative_credentials_before_launch(gate, monkeypatch):
    offline = importlib.import_module("offline_start")
    monkeypatch.setattr(offline, "resolve", lambda: gate.settings)
    monkeypatch.setattr(
        offline, "inspect_settings", lambda *a, **kw: pytest.fail("Must reject before inspection")
    )
    monkeypatch.setattr(sys, "argv", ["offline_start", "worker"])
    with pytest.raises(SystemExit) as rejected:
        offline.main()
    assert rejected.value.code == 2
