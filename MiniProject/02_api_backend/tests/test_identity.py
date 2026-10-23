"""Identity, CSRF, private execution and shared-source lifecycle acceptance."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from youtube_backend import database as db
from youtube_backend.auth import hashed, verify_google
from youtube_backend.auth_cli import bootstrap, claim_legacy, paired_backup
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.fixture_adapter import FixtureAdapters
from youtube_backend.integrations import ExecutionContext
from youtube_backend.main import create_app
from youtube_backend.migration import alembic_config, upgrade_database

VIDEO = "dQw4w9WgXcQ"
ORIGIN = "http://localhost:3000"


@pytest.fixture
def identity(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=True,
        session_cookie_secure=False,
        google_client_id="test-client",
        adapter_mode="fixture",
        job_retry_base_seconds=0,
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        chroma_persist_dir=str(tmp_path / "chroma"),
    )
    database = Database(settings.database_url)
    upgrade_database(database)
    from youtube_backend.repository import Repository

    repo = Repository(database, settings)
    app = create_app(settings, database, FixtureAdapters(repo, settings))
    with TestClient(app) as transport:
        env = SimpleNamespace(
            settings=settings,
            db=database,
            repo=repo,
            app=app,
            worker=app.state.worker,
            transport=transport,
        )
        yield env


def login(env, sub, *, client=None, email=None):
    client = client or TestClient(env.app)
    challenge = client.get("/api/auth/challenge")
    assert challenge.status_code == 200, challenge.text
    data = challenge.json()
    env.app.state.auth.verifier = lambda token, audience: dict(
        sub=sub,
        aud=audience,
        iss="https://accounts.google.com",
        exp=time.time() + 300,
        nonce=data["nonce"],
        email=email or f"{sub}@example.com",
        name=f"Member {sub}",
    )
    response = client.post(
        "/api/auth/google",
        headers={"Origin": ORIGIN},
        json={"credential": "test-credential", "csrf_token": data["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]})
    return client, response.json()["user"]


def ready(env, client):
    imported = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
    assert imported.status_code == 202, imported.text
    job_id = imported.json()["jobs"][0]["job_id"]
    asyncio.run(env.worker.run_once(job_id))
    assert client.get(f"/api/jobs/{job_id}").json()["stage"] == "ready"
    return job_id


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/videos", None),
        ("get", f"/api/videos/{VIDEO}/transcript", None),
        ("get", "/api/jobs/unknown", None),
        ("post", "/api/jobs/unknown/cancel", {}),
        ("post", "/api/jobs/unknown/retry", {}),
        ("get", "/api/research/unknown", None),
        ("get", "/api/learning-artifacts/unknown", None),
        ("get", "/api/conversations/unknown", None),
        ("get", "/api/admin/users", None),
        ("post", "/api/chat", {}),
        ("post", "/api/videos/import", {}),
    ],
)
def test_all_data_routes_require_session(identity, method, path, body):
    assert identity.transport.request(method, path, json=body).status_code == 401


def test_google_sub_relogin_rotation_csrf_and_logout(identity):
    client, user = login(identity, "a")
    old_cookie = client.cookies.get("yk_session")
    assert user["role"] == "user"
    csrf = client.headers["X-CSRF-Token"]
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/videos/import", json={"urls": []}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.post("/api/auth/logout", headers={"Origin": "https://attacker.example"}).status_code
        == 403
    )
    client, again = login(identity, "a", client=client, email="changed@example.com")
    assert again["user_id"] == user["user_id"] and again["email"] == "changed@example.com"
    assert client.cookies.get("yk_session") != old_cookie
    with identity.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.users)) == 1
        assert c.scalar(
            sa.select(db.sessions.c.revoked).where(db.sessions.c.token_hash == hashed(old_cookie))
        )
        assert c.scalar(
            sa.select(db.sessions.c.token_hash).where(db.sessions.c.revoked.is_(False))
        ) != client.cookies.get("yk_session")
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("failure", ["csrf", "nonce", "aud", "iss", "exp", "verifier", "extra"])
def test_bad_login_is_rejected(identity, failure):
    client = TestClient(identity.app)
    challenge = client.get("/api/auth/challenge").json()
    claims = dict(
        sub="a",
        aud="test-client",
        iss="https://accounts.google.com",
        exp=time.time() + 60,
        nonce=challenge["nonce"],
    )
    if failure in {"aud", "iss", "nonce"}:
        claims[failure] = "wrong"
    if failure == "exp":
        claims["exp"] = time.time() - 10

    def verify(*args):
        if failure == "verifier":
            raise ValueError("SECRET must not leak")
        return claims

    identity.app.state.auth.verifier = verify
    body = dict(credential="test", csrf_token=challenge["csrf_token"])
    if failure == "csrf":
        body["csrf_token"] = "x" * 43
    if failure == "extra":
        body["role"] = "admin"
    response = client.post("/api/auth/google", headers={"Origin": ORIGIN}, json=body)
    assert response.status_code in {401, 403, 422}
    assert "SECRET" not in response.text


def test_cross_account_resources_idempotency_and_shared_detach(identity):
    a, user_a = login(identity, "a")
    b, user_b = login(identity, "b")
    original_job = ready(identity, a)
    assert b.get("/api/videos").json()["total"] == 0
    assert b.get(f"/api/videos/{VIDEO}/transcript").status_code == 404
    for path in [
        f"/api/jobs/{original_job}",
        f"/api/jobs/{original_job}/cancel",
        f"/api/jobs/{original_job}/retry",
    ]:
        response = b.get(path) if not path.endswith(("cancel", "retry")) else b.post(path)
        assert response.status_code == 404, response.text
    scope = {"video_ids": [VIDEO]}
    assert b.post("/api/chat", json={"question": "RAG", "scope": scope}).status_code == 404
    b_import = b.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]}).json()
    assert b_import["jobs"][0]["job_id"] != original_job
    assert b.get(f"/api/jobs/{original_job}").status_code == 404
    results = []
    for client in (a, b):
        response = client.post(
            "/api/chat",
            headers={"Idempotency-Key": "same-key"},
            json={"question": "RAG", "scope": scope},
        )
        assert response.status_code == 200, response.text
        results.append(response.json())
    assert results[0]["job_id"] != results[1]["job_id"]
    assert b.get(f"/api/conversations/{results[0]['conversation_id']}").status_code == 404
    assert (
        b.post(
            "/api/chat",
            json={
                "question": "RAG",
                "scope": scope,
                "conversation_id": results[0]["conversation_id"],
            },
        ).status_code
        == 404
    )
    research = a.post("/api/research", json={"goal": "RAG", "scope": scope}).json()["job_id"]
    assert b.get(f"/api/research/{research}").status_code == 404
    assert b.post(f"/api/research/{research}/cancel").status_code == 404
    artifact = a.post("/api/learning-artifacts", json={"type": "quiz", "scope": scope}).json()[
        "job_id"
    ]
    asyncio.run(identity.worker.run_once(artifact))
    result = a.get(f"/api/jobs/{artifact}").json()
    assert result["state"] == "completed", result
    assert (
        b.get(f"/api/learning-artifacts/{result['result']['artifact_ids'][0]}").status_code == 404
    )
    deleted = a.delete(f"/api/videos/{VIDEO}")
    assert deleted.status_code == 202, deleted.text
    assert a.get(f"/api/videos/{VIDEO}/transcript").status_code == 404
    assert b.get(f"/api/videos/{VIDEO}/transcript").status_code == 200
    assert not a.get(f"/api/conversations/{results[0]['conversation_id']}").json()["messages"][1][
        "citations"
    ][0]["source_available"]
    final = b.delete(f"/api/videos/{VIDEO}").json()["job_id"]
    asyncio.run(identity.worker.run_once(final))
    assert b.get(f"/api/jobs/{final}").json()["state"] == "completed"


def test_admin_roles_suspend_expiry_and_no_private_content_bypass(identity):
    a, admin_user = login(identity, "admin")
    b, user = login(identity, "user")
    assert a.get("/api/admin/users").status_code == 403
    bootstrap(identity.db, "admin")
    assert a.get("/api/auth/me").status_code == 401
    a, _ = login(identity, "admin", client=a)
    assert a.get("/api/admin/users").status_code == 200
    assert (
        a.post(f"/api/admin/users/{admin_user['user_id']}", json={"role": "user"}).status_code
        == 409
    )
    private_job = ready(identity, b)
    assert a.get(f"/api/jobs/{private_job}").status_code == 404
    stats = a.get("/api/admin/stats").json()
    assert set(stats) == {"users", "jobs"}
    assert (
        a.post(f"/api/admin/users/{user['user_id']}", json={"status": "suspended"}).status_code
        == 200
    )
    assert b.get("/api/auth/me").status_code == 401
    with identity.db.write() as c:
        c.execute(
            db.sessions.update()
            .where(db.sessions.c.user_id == admin_user["user_id"])
            .values(expires_at=0)
        )
        assert c.scalar(sa.select(sa.func.count()).select_from(db.admin_audit)) == 2
    assert a.get("/api/auth/me").status_code == 401


def test_execution_revokes_sources_and_cannot_read_arbitrary_scope(identity):
    a, user = login(identity, "a")
    ready(identity, a)
    accepted = a.post(
        "/api/analysis", json={"type": "summary", "scope": {"video_ids": [VIDEO]}}
    ).json()
    job = identity.repo.claim(accepted["job_id"])
    context = ExecutionContext(
        identity.repo, job["job_id"], job["lease_token"], job["deadline_at"], identity.settings
    )
    assert context.user_id == user["user_id"]
    from youtube_backend.schemas import Source

    authorized = [Source.model_validate(s) for s in job["payload"]["sources"]]
    assert context.authorize_sources(authorized)
    with pytest.raises(AppError):
        context.authorize_sources(
            [Source(video_id="jNQXAC9IVRw", generation=1, transcript_version="x")]
        )
    removal = a.delete(f"/api/videos/{VIDEO}").json()
    assert identity.repo.claim(removal["job_id"]) is None  # running reader fences GC
    with pytest.raises(AppError):
        context.check()

    identity.repo.fail(job["job_id"], job["lease_token"], AppError("cancelled", "cancelled", 409))
    asyncio.run(identity.worker.run_once(removal["job_id"]))
    assert a.get(f"/api/jobs/{removal['job_id']}").json()["state"] == "completed"


def test_google_library_checks_signature_audience_issuer_and_expiry(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt, jwt
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    monkeypatch.setattr(
        Request,
        "__call__",
        lambda *a, **k: SimpleNamespace(
            status=200, data=json.dumps({"test-key": public.decode()}).encode()
        ),
    )
    signer = crypt.RSASigner.from_string(private)
    claims = dict(
        sub="subject",
        aud="test-client",
        iss="https://accounts.google.com",
        iat=int(time.time()),
        exp=int(time.time()) + 300,
    )

    def encode(values):
        return jwt.encode(signer, values, key_id="test-key").decode()

    assert verify_google(encode(claims), "test-client")["sub"] == "subject"
    for change in ({"aud": "attacker"}, {"iss": "https://attacker"}, {"exp": 1}):
        with pytest.raises((ValueError, GoogleAuthError)):
            verify_google(encode({**claims, **change}), "test-client")
    token = encode(claims)
    header, payload, signature = token.split(".")
    with pytest.raises((ValueError, GoogleAuthError)):
        verify_google(f"{header}.{payload}.invalid{signature}", "test-client")


def test_legacy_upgrade_backup_and_explicit_claim(tmp_path):
    from alembic import command

    path = tmp_path / "legacy.db"
    settings = Settings(
        _env_file=None,
        auth_enabled=True,
        google_client_id="test-client",
        session_cookie_secure=False,
        app_env="test",
        adapter_mode="fixture",
        database_url=f"sqlite:///{path.as_posix()}",
        chroma_persist_dir=str(tmp_path / "chroma"),
    )
    database = Database(settings.database_url)
    with database.engine.begin() as c:
        command.upgrade(alembic_config(c), "0001")
        c.execute(
            db.videos.insert().values(
                video_id=VIDEO,
                canonical_url=f"https://youtu.be/{VIDEO}",
                title="Legacy private video",
                status="ready",
                generation=1,
                transcript_version="legacy",
                indexed_version="legacy",
                created_at=1,
                updated_at=1,
            )
        )
        c.execute(db.conversations.insert().values(conversation_id="legacy-history", created_at=1))
    with pytest.raises(RuntimeError, match="backup"):
        upgrade_database(database)
    with database.engine.begin() as c:
        c.execute(db.videos.update().where(db.videos.c.video_id == VIDEO).values(status="deleting"))
    with pytest.raises(ValueError, match="Finish committed deletions"):
        paired_backup(settings, tmp_path / "blocked-backup")
    assert not (tmp_path / "blocked-backup").exists()
    with database.engine.begin() as c:
        c.execute(db.videos.update().where(db.videos.c.video_id == VIDEO).values(status="ready"))
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    (chroma / "pair-marker").write_bytes(b"preserve-index-and-marker")
    paired_backup(settings, tmp_path / "backup")
    upgrade_database(database, allow_legacy=True)
    app = create_app(settings, database)
    env = SimpleNamespace(app=app, db=database)
    client, user = login(env, "new")
    assert client.get("/api/videos").json()["total"] == 0
    assert client.get("/api/conversations/legacy-history").status_code == 404
    blocked = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
    # CSRF/origin were set by login; knowing an old video ID cannot claim its legacy data.
    assert blocked.json()["jobs"][0]["outcome"] == "rejected"
    assert (chroma / "pair-marker").read_bytes() == (
        tmp_path / "backup/chroma/pair-marker"
    ).read_bytes()
    bootstrap(database, "new")
    claim_legacy(database, admin_sub="new", owner_sub="new")
    client, _ = login(env, "new", client=client)
    assert client.get("/api/videos").json()["total"] == 1
    assert client.get("/api/conversations/legacy-history").status_code == 200
    assert user["role"] == "user"  # first login never bootstraps admin
    database.close()


def test_shared_pending_import_has_private_jobs_and_survives_first_detach(identity):
    a, _ = login(identity, "a")
    b, _ = login(identity, "b")

    def submit(client):
        response = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
        assert response.status_code == 202
        return response.json()["jobs"][0]["job_id"]

    job_a, job_b = submit(a), submit(b)
    assert job_a != job_b
    assert identity.repo.claim(job_b) is None
    assert a.post(f"/api/jobs/{job_a}/cancel").status_code == 409
    a.delete(f"/api/videos/{VIDEO}")
    asyncio.run(identity.worker.run_once(job_a))
    asyncio.run(identity.worker.run_once(job_b))
    assert b.get(f"/api/jobs/{job_b}").json()["stage"] == "ready"
    assert b.get(f"/api/videos/{VIDEO}/transcript").status_code == 200
    assert a.get(f"/api/videos/{VIDEO}/transcript").status_code == 404


def test_challenges_are_single_use_rate_limited_and_cookies_are_hardened(identity):
    client = TestClient(identity.app)
    challenge = client.get("/api/auth/challenge")
    cookie = challenge.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    body = dict(credential="invalid", csrf_token=challenge.json()["csrf_token"])
    identity.app.state.auth.verifier = lambda *args: {}
    assert client.post("/api/auth/google", headers={"Origin": ORIGIN}, json=body).status_code == 401
    assert client.post("/api/auth/google", headers={"Origin": ORIGIN}, json=body).status_code == 403
    for _ in range(29):
        assert client.get("/api/auth/challenge").status_code == 200
    assert client.get("/api/auth/challenge").status_code == 429
    secure = Settings(
        _env_file=None, app_env="production", auth_enabled=True, web_origin="https://example.com"
    )
    from youtube_backend.auth import AuthService

    hardened = AuthService(identity.db, secure)
    assert hardened.cookie.startswith("__Host-") and hardened.cookie_options()["secure"]
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="production", auth_enabled=False)
    with pytest.raises(ValueError) as invalid:
        Settings(
            _env_file=None,
            app_env="production",
            session_cookie_secure=False,
            gemini_api_key="SENTINEL_CONFIG_SECRET",
        )
    assert "SENTINEL_CONFIG_SECRET" not in str(invalid.value)


def test_retry_never_returns_another_subscribers_physical_job(identity):
    a, _ = login(identity, "a")
    b, _ = login(identity, "b")
    body = {"urls": [f"https://youtu.be/{VIDEO}"]}
    first = a.post("/api/videos/import", json=body).json()["jobs"][0]["job_id"]
    claimed = identity.repo.claim(first)
    identity.repo.fail(
        first,
        claimed["lease_token"],
        AppError("timeout", "retryable", 504, True),
        deadline_exhausted=True,
    )
    other = b.post("/api/videos/import", json=body).json()["jobs"][0]["job_id"]
    retry = a.post(f"/api/jobs/{first}/retry")
    assert retry.status_code == 202, retry.text
    assert retry.json()["job_id"] not in {first, other}
    assert a.get(f"/api/jobs/{other}").status_code == 404
    assert a.get(f"/api/jobs/{retry.json()['job_id']}").json()["kind"] == "attach"


def test_unowned_development_data_cannot_be_implicitly_adopted(identity):
    client, _ = login(identity, "new-user")
    with identity.db.write() as c:
        c.execute(
            db.videos.insert().values(
                video_id=VIDEO,
                canonical_url=f"https://youtu.be/{VIDEO}",
                title="Unowned development data",
                status="ready",
                generation=1,
                created_at=1,
                updated_at=1,
            )
        )
    response = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
    assert response.json()["jobs"][0]["outcome"] == "rejected"
    assert client.get("/api/videos").json()["total"] == 0
