import importlib.util
import json
import os
import subprocess
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


def test_verification_plan_includes_full_backend_suite(tmp_path):
    plan = dict(load("check").commands("baseline", tmp_path))
    assert "02_api_backend/full/tests" in plan["02-full"]


def test_runner_keeps_reports_in_runtime_and_uses_selected_short_temp_root(tmp_path, monkeypatch):
    check = load("check")
    monkeypatch.setattr(check, "MODULE", tmp_path / "workspace")
    captured = []
    monkeypatch.setattr(
        check,
        "commands",
        lambda *args: iter(
            [
                ("probe", [sys.executable, "-m", "pytest"]),
            ]
        ),
    )
    monkeypatch.setattr(
        check, "run_command", lambda args, *rest: captured.append(args) or (0, b"passed")
    )
    short = tmp_path / "t"
    monkeypatch.setattr(sys, "argv", ["check", "--temp-root", str(short)])
    assert check.main() == 0
    base = Path(captured[0][captured[0].index("--basetemp") + 1])
    assert base.is_relative_to(short) and not base.is_relative_to(check.MODULE)
    report = json.loads(next((check.MODULE / "runtime").glob("*/report.json")).read_text())
    assert report["complete"] and report["passed"]
    assert Path(report["temporary_state"]).is_relative_to(short)


def test_preflight_cli_initializes_guarded_pair_from_selected_snapshot(tmp_path):
    selected = tmp_path / "full.env"
    selected.write_text(
        f"DATABASE_URL=sqlite:///{(tmp_path / 'state/app.db').as_posix()}\n"
        f"CHROMA_PERSIST_DIR={(tmp_path / 'state/chroma').as_posix()}\n"
        "GEMINI_API_KEY=synthetic-only\nLLM_MODEL=config-only\n",
        encoding="utf-8",
    )
    check = load("check")
    env = check.clean_environment()
    env.pop("GEMINI_API_KEY")  # Explicit selected file is the only key source here.
    args = [
        sys.executable,
        str(MODULE / "scripts/preflight.py"),
        "--env-file",
        str(selected),
        "--require-key",
        "--initialize",
    ]
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30, check=True)
    report = json.loads(result.stdout)
    assert report["pair_verified"] and report["llm_model"] == "config-only"
    assert "synthetic-only" not in result.stdout + result.stderr
    from youtube_backend.full_pair import check_pair

    preflight = load("preflight")
    with preflight.exported(preflight.resolve(selected)):
        assert check_pair(preflight.resolve(selected))["pair_id"]


def test_preflight_restores_process_settings_after_inspection(tmp_path):
    selected = tmp_path / "full.env"
    selected.write_text("LLM_MODEL=only-in-snapshot\n", encoding="utf-8")
    before = dict(os.environ)
    load("preflight").inspect(env_file=selected)
    assert dict(os.environ) == before
