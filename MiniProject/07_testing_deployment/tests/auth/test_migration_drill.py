"""Legacy migration + cold restore on a copy of real fixture SQLite/Chroma data."""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_legacy_migration_operator_bootstrap_claim_and_paired_restore(tmp_path):
    from alembic import command
    from fastapi.testclient import TestClient
    from youtube_backend.config import Settings
    from youtube_backend.database import Database
    from youtube_backend.main import create_app
    from youtube_backend.migration import alembic_config
    from youtube_rag.evaluation import evaluate

    assert "auth_enabled" in Settings.model_fields, "Auth contract required"
    module = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "migration_recovery07", module / "scripts/recovery.py"
    )
    recovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recovery)
    state = tmp_path / "legacy"
    await evaluate(state)
    database = Database(f"sqlite:///{(state / 'app.db').as_posix()}")
    # No users were seeded. Only this disposable fixture is downgraded to construct
    # actual legacy data; production rollback must always restore a stopped pair.
    with database.engine.begin() as connection:
        command.downgrade(alembic_config(connection), "0001")
    database.close()
    before = recovery.backup(state, tmp_path / "pre-migration", stopped=True)
    env = dict(
        os.environ,
        APP_ENV="test",
        ADAPTER_MODE="fixture",
        AUTH_ENABLED="true",
        DATABASE_URL=f"sqlite:///{(state / 'app.db').as_posix()}",
        CHROMA_PERSIST_DIR=str(state / "chroma"),
        SESSION_COOKIE_SECURE="false",
        GOOGLE_CLIENT_ID="migration07",
        GEMINI_API_KEY="",
        OPENAI_API_KEY="",
    )

    def operator(*arguments):
        result = subprocess.run(
            [sys.executable, "-m", "youtube_backend.auth_cli", *arguments],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stderr

    operator("migrate", "--workers-stopped", "--backup-dir", str(tmp_path / "operator-backup"))
    for name, checksum in before["files"].items():
        if name.startswith("chroma/"):
            assert recovery.digest(state / name) == checksum
    assert json.loads((tmp_path / "operator-backup/backup.json").read_text())

    def settings(path):
        return Settings(
            _env_file=None,
            app_env="test",
            adapter_mode="fixture",
            auth_enabled=True,
            session_cookie_secure=False,
            google_client_id="migration07",
            database_url=f"sqlite:///{(path / 'app.db').as_posix()}",
            chroma_persist_dir=str(path / "chroma"),
        )

    def login(client, app):
        challenge = client.get("/api/auth/challenge").json()
        app.state.auth.verifier = lambda token, audience: dict(
            sub="migration-owner",
            aud=audience,
            iss="https://accounts.google.com",
            exp=time.time() + 60,
            nonce=challenge["nonce"],
        )
        response = client.post(
            "/api/auth/google",
            headers={"Origin": "http://localhost:3000"},
            json=dict(credential="fixture", csrf_token=challenge["csrf_token"]),
        )
        assert response.status_code == 200, response.text
        return response.json()["user"]

    app = create_app(settings(state))
    with TestClient(app) as client:
        assert login(client, app)["role"] == "user"
        assert client.get("/api/videos").json()["total"] == 0
        operator("bootstrap-admin", "--google-sub", "migration-owner")
        assert client.get("/api/auth/me").status_code == 401
        operator("claim-legacy", "--admin-sub", "migration-owner", "--owner-sub", "migration-owner")
        assert login(client, app)["role"] == "admin"
        owned = client.get("/api/videos").json()["total"]
        assert owned > 0
    recovery.backup(state, tmp_path / "migrated-backup", stopped=True)
    restored = tmp_path / "restored"
    recovery.restore(tmp_path / "migrated-backup", restored)
    app = create_app(settings(restored))
    with TestClient(app) as client:
        assert login(client, app)["role"] == "admin"
        assert client.get("/api/videos").json()["total"] == owned
        assert client.get("/health").json()["schema_revision"] == "0004"
    rollback = tmp_path / "rollback-copy"
    recovery.restore(tmp_path / "pre-migration", rollback)
    import sqlite3

    with sqlite3.connect(rollback / "app.db") as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001"
    for name, checksum in before["files"].items():
        if name.startswith("chroma/"):
            assert recovery.digest(rollback / name) == checksum
