import importlib.util
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, MODULE / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_suite_timeout_is_nonzero_and_retains_output():
    check = load("check")
    code, log = check.run_command(
        [sys.executable, "-u", "-c", "import time; print('started'); time.sleep(30)"],
        check.clean_environment(),
        1,
    )
    assert code == 124 and b"started" in log and b"SUITE TIMEOUT" in log


def test_offline_environment_disables_explicit_provider_opt_in(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-inherit")
    monkeypatch.setenv("RUN_LIVE_EMBEDDING_TESTS", "1")
    check = load("check")
    env = check.clean_environment()
    assert env["GEMINI_API_KEY"] == env["OPENAI_API_KEY"] == ""
    assert env["RUN_LIVE_EMBEDDING_TESTS"] == "0"


def test_preflight_accepts_explicit_shared_live_configuration_without_network(
    monkeypatch, tmp_path
):
    for name, value in dict(
        ADAPTER_MODE="custom",
        ADAPTER_FACTORY="youtube_answers.team:create_adapters",
        BACKEND_INTEGRATION_PROFILE="live",
        EMBEDDING_PROVIDER="gemini",
        EMBEDDING_MODEL="gemini-embedding-2",
        GEMINI_API_KEY="synthetic-not-a-real-key",
        LLM_MODEL="fixture-config-only",
        CHROMA_PERSIST_DIR=str(tmp_path / "chroma"),
        DATABASE_URL=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
    ).items():
        monkeypatch.setenv(name, value)
    report = load("preflight").inspect(require_key=True)
    assert report["chroma_persist_dir"] == str(tmp_path / "chroma")
    assert not report["provider_access_verified"]
    assert "synthetic-not-a-real-key" not in str(report)
    assert not (tmp_path / "app.db").exists()


def test_live_smoke_refuses_calls_without_opt_in(monkeypatch):
    live = load("live_smoke")
    monkeypatch.setattr(
        sys, "argv", ["live_smoke", "--url", "https://youtu.be/dQw4w9WgXcQ", "--question", "RAG?"]
    )
    monkeypatch.setattr(live, "request", lambda *args: pytest.fail("Unexpected network request"))
    with pytest.raises(SystemExit) as caught:
        live.main()
    assert caught.value.code == 2
