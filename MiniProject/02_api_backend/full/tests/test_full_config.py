"""Full launcher contract and SQLite/Chroma binding regression checks."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from youtube_backend.full import FACTORY, FullSettings
from youtube_backend.full_pair import MARKER, check_pair, initialize_pair


@pytest.fixture
def config(tmp_path):
    return FullSettings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        chroma_persist_dir=str(tmp_path / "chroma"),
    )


def test_config_exports_every_service_field_and_redacts_keys(config, monkeypatch, tmp_path):
    config = FullSettings(**{**config.model_dump(), "gemini_api_key": "DO_NOT_PRINT"})
    file = tmp_path / "module.env"
    file.write_text("LLM_MODEL=wrong\nCHROMA_PERSIST_DIR=wrong\nGEMINI_API_KEY=wrong\n")
    for key, value in config.child_environment({}).items():
        monkeypatch.setenv(key, value)
    for service in config.services().values():
        reloaded = type(service)(_env_file=file)
        for field in type(service).model_fields:
            assert getattr(reloaded, field) == getattr(service, field), field
    summary = json.dumps(config.summary())
    assert "DO_NOT_PRINT" not in summary
    assert config.summary()["gemini_key_configured"]
    assert not config.summary()["live_provider_verified"]


def test_selected_file_overridden_only_by_process_environment(config, monkeypatch, tmp_path):
    file = tmp_path / "full.env"
    file.write_text("LLM_MODEL=file-model\nANSWER_MAX_CHUNKS=123\n")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    selected = FullSettings(_env_file=file)
    assert selected.llm_model == "file-model"
    assert selected.answer_max_chunks == 123
    monkeypatch.setenv("LLM_MODEL", "process-model")
    assert FullSettings(_env_file=file).llm_model == "process-model"


@pytest.mark.parametrize(
    "change",
    [
        {"backend_integration_profile": "offline"},
        {"adapter_factory": "youtube_backend.team:create_adapters"},
        {"embedding_provider": "fixture"},
        {"adapter_mode": "fixture"},
    ],
)
def test_full_profile_is_explicit(change):
    with pytest.raises(ValidationError):
        FullSettings(_env_file=None, **change)


@pytest.mark.parametrize(
    "change",
    [
        {"answer_max_model_calls": 0},
        {"transcript_languages": "bad_language"},
        {"metadata_provider": "unknown"},
        {"embedding_model": "wrong"},
        {"agent_finalize_reserve_seconds": 120, "agent_timeout_seconds": 120},
    ],
)
def test_service_validation_happens_before_initialization(change):
    with pytest.raises(ValidationError):
        FullSettings(_env_file=None, **change).services()


def test_pair_repeatable_wrong_path_and_wrong_embedding_rejected(config, tmp_path):
    record = initialize_pair(config)
    assert record == initialize_pair(config) == check_pair(config)
    other = config.model_copy(update={"chroma_persist_dir": str(tmp_path / "other")})
    with pytest.raises(FileNotFoundError):
        check_pair(other)
    assert not (tmp_path / "other").exists()
    changed = config.model_copy(update={"embedding_dimensions": 128})
    with pytest.raises(ValueError, match="configuration changed"):
        check_pair(changed)
    assert check_pair(config) == record


def test_two_initialized_pairs_cannot_exchange_directories(config, tmp_path):
    initialize_pair(config)
    other = FullSettings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'other.db').as_posix()}",
        chroma_persist_dir=str(tmp_path / "other-chroma"),
    )
    initialize_pair(other)
    with pytest.raises(ValueError, match="does not match"):
        check_pair(config.model_copy(update={"chroma_persist_dir": other.chroma_persist_dir}))


@pytest.mark.parametrize("existing", ["database", "chroma"])
def test_unbound_existing_data_is_never_adopted(config, existing, tmp_path):
    if existing == "database":
        path = tmp_path / "app.db"
        path.write_bytes(b"existing database")
    else:
        path = tmp_path / "chroma" / "existing.txt"
        path.parent.mkdir()
        path.write_bytes(b"existing index")
    original = path.read_bytes()
    with pytest.raises((ValueError, SQLAlchemyError)):
        initialize_pair(config)
    assert path.read_bytes() == original
    assert not (tmp_path / "chroma" / MARKER).exists()


def test_missing_check_does_not_create_database_or_index(config, tmp_path):
    with pytest.raises(ValueError):
        check_pair(config)
    assert not (tmp_path / "app.db").exists()
    assert not (tmp_path / "chroma").exists()


def test_sqlite_cannot_be_inside_chroma(tmp_path):
    with pytest.raises(ValidationError):
        FullSettings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'chroma' / 'app.db').as_posix()}",
            chroma_persist_dir=str(tmp_path / "chroma"),
        )


def test_cli_config_init_check_and_preflight_without_secret_leak(config, tmp_path):
    file = tmp_path / "full.env"
    # Use a subprocess environment with all service fields; never send keys as argv.
    file.write_text("# empty selected config\n")
    environment = config.child_environment(os.environ)
    environment["GEMINI_API_KEY"] = ""
    base = [sys.executable, "-m", "youtube_backend.full", "--env-file", str(file)]

    def run(*args):
        return subprocess.run(
            base + list(args), env=environment, capture_output=True, text=True, timeout=30
        )

    summary = run("config")
    assert summary.returncode == 0, summary.stderr
    assert json.loads(summary.stdout)["factory"] == FACTORY
    assert run("check").returncode == 2
    assert run("init").returncode == 0
    assert json.loads(run("check").stdout)["pair_verified"]
    assert run("api").returncode == 2  # key absent; no server or provider started
    assert run("gc").returncode == 2  # explicit stopped assertion is required
    environment["ANSWER_MAX_CHUNKS"] = "SECRET-MALFORMED-CONFIG"
    failed = run("config")
    assert failed.returncode == 2
    assert "SECRET-MALFORMED-CONFIG" not in failed.stderr + failed.stdout
    assert Path(config.chroma_persist_dir, MARKER).is_file()


@pytest.mark.parametrize("command", ["api", "worker", "gc", "reindex"])
def test_launcher_dispatches_identical_environment_without_keys_in_argv(
    config, monkeypatch, tmp_path, command
):
    from youtube_backend import full

    config = FullSettings(**{**config.model_dump(), "gemini_api_key": "test-only-secret"})
    initialize_pair(config)
    file = tmp_path / "full.env"
    file.write_text("# selected empty file\n")
    for key, value in config.child_environment({}).items():
        monkeypatch.setenv(key, value)
    args = ["yk-full", "--env-file", str(file), command]
    if command in {"gc", "reindex"}:
        args += ["--workers-stopped"]
    if command == "reindex":
        args += ["--video-id", "dQw4w9WgXcQ"]
    monkeypatch.setattr(sys, "argv", args)
    captured = {}

    def child(arguments, env):
        captured.update(arguments=arguments, environment=env)
        raise SystemExit(0)

    monkeypatch.setattr(full.subprocess, "call", child)
    monkeypatch.setattr(full.os, "execve", lambda executable, arguments, env: child(arguments, env))
    with pytest.raises(SystemExit) as stopped:
        full.main()
    assert stopped.value.code == 0
    assert "test-only-secret" not in repr(captured["arguments"])
    assert captured["environment"]["GEMINI_API_KEY"] == "test-only-secret"
    for service in config.services().values():
        for field in type(service).model_fields:
            assert field.upper() in captured["environment"]
    assert captured["environment"]["CHROMA_PERSIST_DIR"] == config.chroma_persist_dir
    assert captured["environment"]["DATABASE_URL"] == config.database_url


async def test_runtime_pair_guard_runs_before_constructing_the_factory(
    config, tmp_path, monkeypatch
):
    from youtube_backend import runtime
    from youtube_backend.database import Database
    from youtube_backend.repository import Repository

    initialize_pair(config)
    wrong = config.model_copy(update={"chroma_persist_dir": str(tmp_path / "wrong")})
    database = Database(config.database_url)
    called = []
    monkeypatch.setattr(runtime, "load_adapters", lambda *args: called.append(True))
    instance = runtime.ManagedAdapters(wrong, Repository(database, wrong))
    try:
        with pytest.raises(FileNotFoundError):
            await instance.start()
        assert not called
    finally:
        await instance.close()
        database.close()
