"""Test-only identity injection. Never imported by application startup or Docker runtime."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.fixture_adapter import FixtureAdapters
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository

ORIGIN = "http://localhost:3000"


@pytest.fixture
def identities(tmp_path):
    assert "auth_enabled" in Settings.model_fields, (
        "AUTH BLOCKED: merge module 02 Google identity/ownership before running --group auth"
    )
    from youtube_backend.auth_cli import bootstrap

    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=True,
        session_cookie_secure=False,
        google_client_id="fixture07.apps.googleusercontent.com",
        adapter_mode="fixture",
        job_retry_base_seconds=0,
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        chroma_persist_dir=str(tmp_path / "chroma"),
    )
    assert settings.app_env == "test" and settings.adapter_mode == "fixture"
    database = Database(settings.database_url)
    upgrade_database(database)
    repo = Repository(database, settings)
    app = create_app(settings, database, FixtureAdapters(repo, settings))
    clients = []

    def login(subject, claims=None, extra=None, expect=200, client=None):
        client = client or TestClient(app)
        if client not in clients:
            clients.append(client)
        challenge = client.get("/api/auth/challenge").json()
        values = dict(
            sub=subject,
            aud=settings.google_client_id,
            iss="https://accounts.google.com",
            exp=time.time() + 300,
            nonce=challenge["nonce"],
            email=f"{subject}@example.invalid",
            name=f"Fixture {subject}",
        )
        values.update(claims or {})
        app.state.auth.verifier = lambda credential, audience: values
        response = client.post(
            "/api/auth/google",
            headers={"Origin": ORIGIN},
            json=dict(
                credential="fixture07-never-a-google-token",
                csrf_token=challenge["csrf_token"],
                **(extra or {}),
            ),
        )
        assert response.status_code == expect, response.text
        if expect == 200:
            client.headers["Origin"] = ORIGIN
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client, response

    with TestClient(app):
        a, a_response = login("a")
        b, b_response = login("b")
        admin, response = login("admin")
        assert response.json()["user"]["role"] == "user"
        bootstrap(database, "admin")
        admin, admin_response = login("admin", client=admin)
        suspended, response = login("suspended")
        suspended_id = response.json()["user"]["user_id"]
        assert (
            admin.post(f"/api/admin/users/{suspended_id}", json={"status": "suspended"}).status_code
            == 200
        )
        yield SimpleNamespace(
            a=a,
            b=b,
            admin=admin,
            suspended=suspended,
            login=login,
            users={
                "a": a_response.json()["user"],
                "b": b_response.json()["user"],
                "admin": admin_response.json()["user"],
            },
            app=app,
            worker=app.state.worker,
            db=database,
        )
    for client in clients:
        client.close()


def pytest_collection_modifyitems(items):
    for item in items:
        if "/auth/" in item.path.as_posix():
            item.add_marker(pytest.mark.auth)
