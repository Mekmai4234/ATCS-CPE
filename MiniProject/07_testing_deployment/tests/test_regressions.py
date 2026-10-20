"""Regression gates use supported CLI contracts and assert storage safeguards."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_rag import cli
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


@pytest.mark.parametrize("operation", ["reindex", "gc"])
async def test_wrong_maintenance_store_is_rejected_before_manifest_mutation(tmp_path, operation):
    state = tmp_path / "s"
    await evaluate(state)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(state / 'app.db').as_posix()}",
        adapter_mode="fixture",
        app_env="test",
    )
    database = Database(settings.database_url)

    def snapshot():
        with database.read() as connection:
            return [
                connection.execute(sa.text(f"SELECT * FROM {table}")).all()
                for table in ("rag04_active", "rag04_runs", "rag04_chunks")
            ]

    wrong = tmp_path / "wrong"
    file = tmp_path / "selected.env"
    file.write_text(
        "\n".join(
            [
                "APP_ENV=test",
                f"DATABASE_URL={settings.database_url}",
                "EMBEDDING_PROVIDER=fixture",
                "EMBEDDING_MODEL=fixture-hash-v1",
                "EMBEDDING_DIMENSIONS=128",
                "CHUNK_TARGET_TOKENS=160",
                "CHUNK_OVERLAP_TOKENS=24",
                f"CHROMA_PERSIST_DIR={wrong.as_posix()}",
            ]
        ),
        encoding="utf-8",
    )
    try:
        before = snapshot()
        arguments = [operation, "--workers-stopped", "--env-file", str(file)]
        if operation == "reindex":
            arguments += ["--video-id", before[0][0][0]]
        with pytest.raises(AppError) as caught:
            await cli.maintenance(cli.build_parser().parse_args(arguments))
        assert caught.value.code == "index_store_mismatch"
        assert snapshot() == before
        assert not wrong.exists()
    finally:
        database.close()


def test_runtime_and_maintenance_resolve_identical_rag_config(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    selected = tmp_path / "selected.env"
    selected.write_text(
        "\n".join(
            [
                "DATABASE_URL=sqlite:///./state/app.db",
                "CHROMA_PERSIST_DIR=state/selected-chroma",
                "LLM_MODEL=selected-model",
                "EMBEDDING_DIMENSIONS=256",
            ]
        ),
        encoding="utf-8",
    )
    stale = root / "05_ai_answers_analysis" / ".env"
    stale.parent.mkdir()
    stale.write_text("CHROMA_PERSIST_DIR=wrong\nLLM_MODEL=wrong\n", encoding="utf-8")
    code = """
import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('preflight07',sys.argv[1])
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
print(json.dumps(p.inspect(env_file=sys.argv[2])))
"""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(
            (
                "CHROMA_",
                "EMBEDDING_",
                "LLM_",
                "ADAPTER_",
                "BACKEND_",
            )
        )
        and k.upper() not in {"DATABASE_URL"}
    }
    env["MINIPROJECT_ROOT"] = str(root)
    result = subprocess.run(
        [sys.executable, "-c", code, str(MODULE / "scripts/preflight.py"), str(selected)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["chroma_persist_dir"] == str(root / "state" / "selected-chroma")
    assert observed["database_url"].endswith("state/app.db") or observed["database_url"].endswith(
        "state\\app.db"
    )
    assert observed["llm_model"] == "selected-model"
    assert observed["embedding_dimensions"] == 256
    assert not (root / "state").exists()
