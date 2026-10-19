"""These checks intentionally fail while the upstream release blockers still exist."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_rag import cli
from youtube_rag.config import RagSettings
from youtube_rag.evaluation import evaluate

pytestmark = pytest.mark.regression
MODULE = Path(__file__).resolve().parents[1]


def test_caption_oversize_cleanup_finishes_within_bound():
    result = subprocess.run(
        [sys.executable, str(MODULE / "scripts" / "caption_probe.py")],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["children_reaped"], observed
    assert observed["within_deadline"], observed
    assert observed["error_code"] == "invalid_transcript", observed


async def test_wrong_maintenance_store_is_rejected_before_manifest_mutation(tmp_path, monkeypatch):
    state = tmp_path / "state"
    await evaluate(state)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(state / 'app.db').as_posix()}",
        adapter_mode="fixture",
        app_env="test",
    )
    database = Database(settings.database_url)

    def active_runs():
        with database.read() as connection:
            return list(
                connection.execute(
                    sa.text(
                        "SELECT video_id, generation, run_id FROM rag04_active ORDER BY video_id"
                    )
                )
            )

    try:
        before = active_runs()
        # Same SQLite and embedding identity, but a DIFFERENT empty physical store.
        config = RagSettings(
            _env_file=None,
            embedding_provider="fixture",
            embedding_model="fixture-hash-v1",
            embedding_dimensions=128,
            chunk_target_tokens=160,
            chunk_overlap_tokens=24,
            chroma_persist_dir=tmp_path / "wrong-chroma",
        )
        monkeypatch.setattr(cli, "Settings", lambda: settings)
        monkeypatch.setattr(cli, "RagSettings", lambda: config)
        failure = None
        try:
            await cli.maintenance(
                SimpleNamespace(
                    command="reindex",
                    workers_stopped=True,
                    video_id=before[0][0],
                )
            )
        except Exception as exc:
            failure = exc
        assert failure is not None and active_runs() == before, (
            "Wrong Chroma store was accepted or active manifest changed; "
            "module 04 must validate the SQLite/store pairing before reindex."
        )
    finally:
        database.close()


def test_runtime_and_maintenance_resolve_identical_rag_config(tmp_path):
    from youtube_answers.team import ENV_FILES

    # Inspect resolution in a separate process with an isolated project root. Never
    # overwrite actual module .env files or import-root state in the pytest process.
    root = tmp_path / "project"
    for path in ENV_FILES:
        relative = path.relative_to(MODULE.parent)
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / "05_ai_answers_analysis" / ".env").write_text(
        "CHROMA_PERSIST_DIR=runtime/answers05/chroma\n", encoding="utf-8"
    )
    code = """
import json
from youtube_rag.config import RagSettings
from youtube_answers.team import ENV_FILES
runtime = RagSettings(_env_file=ENV_FILES)
maintenance = RagSettings()
print(json.dumps(dict(runtime=str(runtime.chroma_persist_dir),
                     maintenance=str(maintenance.chroma_persist_dir))))
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CHROMA_", "EMBEDDING_"))}
    env["MINIPROJECT_ROOT"] = str(root)
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["runtime"] == observed["maintenance"], observed
