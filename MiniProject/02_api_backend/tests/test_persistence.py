import asyncio
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from alembic import command
from conftest import VIDEO_A, chat_body
from pydantic import ValidationError

from youtube_backend.config import PROJECT_ROOT, Settings
from youtube_backend.database import Database
from youtube_backend.fixture_adapter import FixtureAdapters
from youtube_backend.main import create_app
from youtube_backend.migration import alembic_config, upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.schemas import Coverage, Segment, TranscriptResult
from youtube_backend.worker import Worker


def test_migrations_are_repeatable_match_models_and_roundtrip(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}")
    upgrade_database(database)
    upgrade_database(database)
    database.check_schema()
    with database.engine.begin() as connection:
        command.check(alembic_config(connection))
        command.downgrade(alembic_config(connection), "base")
    with pytest.raises(RuntimeError, match="schema"):
        database.check_schema()
    upgrade_database(database)
    database.check_schema()
    database.close()


def test_database_requires_explicit_migration(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    with pytest.raises(RuntimeError, match="yk-db upgrade head"):
        database.check_schema()
    database.close()


def test_configuration_paths_and_secrets_are_safe(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, database_url="sqlite:///./runtime/relative-test.db")
    assert str(PROJECT_ROOT / "runtime" / "relative-test.db") in settings.database_url
    settings = Settings(_env_file=None, gemini_api_key="TOP_SECRET_TEST")
    assert "TOP_SECRET_TEST" not in repr(settings)
    for kwargs in [
        {"database_url": "sqlite:///:memory:"},
        {"database_url": "postgresql://localhost/app"},
        {"enable_streaming": True},
        {"adapter_mode": "other"},
        {"adapter_mode": "custom"},
        {"adapter_mode": "fixture", "app_env": "production"},
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **kwargs)


def test_transcript_and_coverage_reject_bad_intervals_and_counts():
    with pytest.raises(ValidationError):
        Segment(segment_id="s", text="x", start_seconds=float("nan"), duration_seconds=1)
    with pytest.raises(ValidationError):
        TranscriptResult(
            video_id=VIDEO_A,
            title="x",
            language="th",
            source="fixture",
            segments=[
                Segment(segment_id="s", text="x", start_seconds=1, duration_seconds=1),
                Segment(segment_id="s", text="y", start_seconds=0, duration_seconds=1),
            ],
        )
    with pytest.raises(ValidationError):
        Coverage(
            expected_videos=2,
            processed_videos=1,
            expected_chunks=3,
            processed_chunks=2,
            complete=True,
        )


def test_chat_and_artifact_persist_after_reopening_database(ready):
    answer = ready.client.post("/api/chat", json=chat_body()).json()
    task = ready.client.post(
        "/api/learning-artifacts", json={"type": "flashcards", "scope": {"video_ids": [VIDEO_A]}}
    ).json()["job_id"]
    asyncio.run(ready.worker.run_once(task))
    artifact_id = ready.repo.get_job(task)["result"]["artifact_ids"][0]
    database = Database(ready.settings.database_url)
    repo = Repository(database, ready.settings)
    assert repo.conversation(answer["conversation_id"], 100, 0)["total"] == 2
    assert repo.artifact(artifact_id)["type"] == "flashcards"
    assert repo.get_job(answer["job_id"])["result"]["answer"] == answer["answer"]
    # A follow-up uses the persisted source versions and bounded, matching history.
    followup = repo.enqueue("chat", chat_body(conversation_id=answer["conversation_id"]))
    assert len(followup["payload"]["history"]) == 2
    asyncio.run(
        Worker(repo, FixtureAdapters(repo, ready.settings), ready.settings).run_once(
            followup["job_id"]
        )
    )
    assert repo.get_job(followup["job_id"])["state"] == "completed"
    database.close()


def test_busy_conversation_and_history_scope_change(ready):
    answer = ready.client.post("/api/chat", json=chat_body()).json()
    conversation_id = answer["conversation_id"]
    job = ready.repo.enqueue("chat", chat_body("jNQXAC9IVRw", conversation_id=conversation_id))
    assert job["payload"]["history"] == []
    response = ready.client.post("/api/chat", json=chat_body(conversation_id=conversation_id))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_busy"
    ready.repo.cancel(job["job_id"])
    assert ready.repo.get_job(job["job_id"])["state"] == "cancelled"


def test_fixture_database_cannot_be_silently_reused_as_live(ready):
    settings = ready.settings.model_copy(update={"adapter_mode": "custom"})
    repo = Repository(ready.db, settings)
    from youtube_backend.errors import AppError

    with pytest.raises(AppError, match="separate DATABASE_URL"):
        repo.check_mode()
    with pytest.raises(AppError, match="separate DATABASE_URL"):
        repo.import_urls(["https://youtu.be/AnotherId01"])
    assert ready.repo.list_videos(100, 0)["total"] == 2


def test_http_and_worker_as_separate_processes_with_restart(tmp_path):
    """Exercise installed CLI entrypoints over real HTTP and a shared file-backed DB."""
    database_path = tmp_path / "process.db"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process_env = dict(
        os.environ,
        APP_ENV="test",
        ADAPTER_MODE="fixture",
        DATABASE_URL=f"sqlite:///{database_path.as_posix()}",
        API_HOST="127.0.0.1",
        API_PORT=str(port),
        ENABLE_STREAMING="false",
    )
    command_base = [sys.executable, "-m", "youtube_backend"]
    kwargs = dict(
        cwd=tmp_path, env=process_env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    migration = subprocess.run(
        command_base + ["db", "upgrade", "head"],
        capture_output=True,
        text=True,
        timeout=15,
        **kwargs,
    )
    assert migration.returncode == 0, migration.stderr
    log_path = tmp_path / "api-output.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command_base + ["api"], stdout=log, stderr=log, **kwargs)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                for _ in range(200):
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if process.poll() is not None:
                        pytest.fail(f"API exited early: {log_path.read_text(encoding='utf-8')}")
                    time.sleep(0.05)
                else:
                    pytest.fail("API did not start")
                imported = client.post(
                    "/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO_A}"]}
                )
                assert imported.status_code == 202
                job_id = imported.json()["jobs"][0]["job_id"]
                # Worker starts AFTER import acceptance and can read the persisted job.
                worker = subprocess.run(
                    command_base + ["worker", "--once"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    **kwargs,
                )
                assert worker.returncode == 0, worker.stderr
                assert client.get(f"/api/jobs/{job_id}").json()["stage"] == "ready"
                answer = client.post("/api/chat", json=chat_body()).json()
                assert answer["status"] == "answered"
                # Simulate a fresh API process against the same database.
                process.terminate()
                process.wait(timeout=10)
                process = subprocess.Popen(command_base + ["api"], stdout=log, stderr=log, **kwargs)
                for _ in range(200):
                    try:
                        response = client.get(f"/api/conversations/{answer['conversation_id']}")
                        if response.status_code == 200:
                            assert response.json()["total"] == 2
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    pytest.fail("API did not recover persisted history")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def test_lifespan_rejects_unmigrated_database(tmp_path):
    from fastapi.testclient import TestClient

    settings = Settings(
        _env_file=None, database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    )
    with pytest.raises(RuntimeError, match="schema"), TestClient(create_app(settings)):
        pass
