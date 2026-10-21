import json
import sys
from types import SimpleNamespace

import pytest
from test_tooling import load


def test_offline_runner_has_explicit_auth_group_and_scrubs_auth_env(monkeypatch, tmp_path):
    check = load("check")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "unrelated")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    environment = check.clean_environment()
    assert not {"AUTH_ENABLED", "GOOGLE_CLIENT_ID", "SESSION_COOKIE_SECURE"} & environment.keys()
    plan = dict(check.commands("auth", tmp_path))
    assert "07_testing_deployment/tests/auth" in plan["07-auth"]
    assert "--ignore" not in plan["07-auth"]


def test_release_rejects_legacy_backend_and_missing_evidence():
    result = load("auth_readiness").check(SimpleNamespace(web_origin="http://localhost:3000"))
    assert not result["auth_release_ready"]
    assert "backend_auth_unavailable_or_disabled" in result["blockers"]
    assert "integrated_release_evidence_missing" in result["blockers"]


def test_auth_preflight_rejects_before_initializing_data(tmp_path, monkeypatch):
    preflight = load("preflight")
    monkeypatch.setitem(sys.modules, "auth_readiness", load("auth_readiness"))
    evidence = tmp_path / "release.json"
    evidence.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(
        preflight, "resolve", lambda path: SimpleNamespace(web_origin="http://local")
    )
    monkeypatch.setattr(preflight, "inspect_settings", lambda *args: {})
    monkeypatch.setattr(
        preflight, "initialize_pair", lambda *args: pytest.fail("Must not initialize")
    )
    monkeypatch.setattr(
        sys, "argv", ["preflight", "--auth-evidence", str(evidence), "--initialize"]
    )
    with pytest.raises(SystemExit) as failure:
        preflight.main()
    assert failure.value.code == 1


def test_release_needs_all_acceptance_evidence_and_safe_cookie_origin():
    check = load("auth_readiness").check
    settings = SimpleNamespace(
        app_env="production",
        adapter_mode="custom",
        adapter_factory="youtube_answers.team:create_adapters",
        backend_integration_profile="live",
        auth_enabled=True,
        google_client_id="public-client-id",
        session_cookie_secure=True,
        web_origin="https://rag.example",
        auth_trusted_origins=["https://rag.example"],
    )
    evidence = dict(
        revision="commit",
        image_digest="sha256:example",
        google_login=True,
        logout_account_switch=True,
        browser_backend_flow=True,
        ownership_suites=True,
        reviewed_by="operator",
        tested_at_utc="2026-10-21",
    )
    assert check(settings, evidence)["auth_release_ready"]
    settings.app_env = "test"
    assert not check(settings, evidence)["auth_release_ready"]
    settings.app_env = "production"
    evidence["browser_backend_flow"] = False
    assert not check(settings, evidence)["auth_release_ready"]
    evidence["browser_backend_flow"] = True
    settings.session_cookie_secure = False
    assert not check(settings, evidence)["auth_release_ready"]
