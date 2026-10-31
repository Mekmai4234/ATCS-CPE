"""Native 02 session/jobs + 03 captions + 04 SQLite/Chroma integration.

Only Google verification, captions/metadata and vector values are provider doubles.
There is no fake membership backend or alternate authorization implementation.
"""

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B
from test_integration import Captions, Meta
from youtube_backend import database as db
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.schemas import Source
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import initialize

from youtube_ingestion.integration import IngestionAdapters
from youtube_ingestion.member_adapters import create_member_adapters
from youtube_ingestion.service import IngestionService

ORIGIN = "http://localhost:3000"


async def login(app, client, sub):
    response = await client.get("/api/auth/challenge")
    assert response.status_code == 200, response.text
    challenge = response.json()
    app.state.auth.verifier = lambda token, audience: dict(
        sub=sub,
        aud=audience,
        iss="https://accounts.google.com",
        exp=time.time() + 300,
        nonce=challenge["nonce"],
        email=f"{sub}@example.invalid",
        name=f"[FIXTURE] {sub}",
    )
    response = await client.post(
        "/api/auth/google",
        headers={"Origin": ORIGIN},
        json={"credential": "fixture-only", "csrf_token": challenge["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]})
    return response.json()["user"]


@pytest.fixture
async def members(tmp_path, config):
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=True,
        session_cookie_secure=False,
        google_client_id="03-test-client",
        adapter_mode="custom",
        adapter_factory="youtube_ingestion.member_adapters:create_member_adapters",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        job_retry_base_seconds=0,
        job_lease_seconds=30,
        job_timeout_seconds=60,
    )
    database = Database(settings.database_url)
    upgrade_database(database)
    initialize(database)
    rag_config = RagSettings(
        _env_file=None,
        embedding_provider="fixture",
        embedding_model="fixture-hash-v1",
        embedding_dimensions=64,
        chroma_persist_dir=tmp_path / "chroma",
        chunk_target_tokens=96,
        chunk_overlap_tokens=16,
    )
    knowledge = RagAdapters(
        settings=settings,
        repository=Repository(database, settings),
        rag_settings=rag_config,
        embedder=FixtureEmbedder(rag_config),
    )
    captions = Captions()
    ingestion = IngestionService(config, captions=captions, metadata=Meta())
    adapters = IngestionAdapters(ingestion, knowledge)
    app = create_app(settings, database, adapters)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test") as a,
            httpx.AsyncClient(transport=transport, base_url="http://test") as b,
            httpx.AsyncClient(transport=transport, base_url="http://test") as guest,
        ):
            user_a = await login(app, a, "member-a")
            user_b = await login(app, b, "member-b")
            yield SimpleNamespace(
                app=app,
                a=a,
                b=b,
                guest=guest,
                user_a=user_a,
                user_b=user_b,
                db=database,
                repo=app.state.repository,
                worker=app.state.worker,
                adapters=adapters,
                captions=captions,
                settings=settings,
                rag_config=rag_config,
            )


async def add(client, video=VIDEO_A):
    response = await client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{video}"]})
    assert response.status_code == 202, response.text
    return response.json()["jobs"][0]["job_id"]


async def poll(client, job):
    response = await client.get(f"/api/jobs/{job}")
    assert response.status_code == 200, response.text
    return response.json()


async def ready(env, client, video=VIDEO_A):
    job = await add(client, video)
    assert await env.worker.run_once(job)
    assert (await poll(client, job))["stage"] == "ready"
    return job


async def vector_count(env):
    return await env.adapters.knowledge.rag.vectors.call("count", 15)


@pytest.mark.parametrize("attach_first", [False, True])
async def test_concurrent_accounts_share_source_with_private_jobs(members, attach_first):
    env = members
    a, b = await asyncio.gather(add(env.a), add(env.b))
    assert a != b
    assert (await env.b.get(f"/api/jobs/{a}")).status_code == 404
    assert (await env.a.get(f"/api/jobs/{b}")).status_code == 404
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.videos)) == 1
        assert c.scalar(sa.select(sa.func.count()).select_from(db.user_videos)) == 2
        assert (
            c.scalar(
                sa.select(sa.func.count()).select_from(db.jobs).where(db.jobs.c.kind == "import")
            )
            == 1
        )
    # asyncio.gather preserves argument order, not which account acquired the
    # shared import first. Process by dependency, never by account position.
    jobs = {env.repo.get_job(job, internal=True)["kind"]: job for job in (a, b)}
    assert set(jobs) == {"import", "attach"}
    if attach_first:
        assert not await env.worker.run_once(jobs["attach"])
        waiting = env.repo.get_job(jobs["attach"], internal=True)
        assert waiting["state"] == "queued" and waiting["attempt_count"] == 0
    assert await env.worker.run_once(jobs["import"])
    assert await env.worker.run_once(jobs["attach"])
    assert (await poll(env.a, a))["stage"] == (await poll(env.b, b))["stage"] == "ready"
    assert env.captions.calls == [VIDEO_A]
    assert await vector_count(env) > 0
    for client in (env.a, env.b):
        response = await client.get(f"/api/videos/{VIDEO_A}/transcript")
        assert response.status_code == 200
        assert response.json()["segments"][1]["start_seconds"] == 12


async def test_ready_reuse_detach_rejoin_and_final_gc_reimport(members):
    env = members
    a = await ready(env, env.a)
    count = await vector_count(env)
    b = await add(env.b)
    assert b != a and (await poll(env.b, b))["stage"] == "ready"
    assert env.captions.calls == [VIDEO_A]
    removed = await env.a.delete(f"/api/videos/{VIDEO_A}")
    assert removed.status_code == 202
    assert (await poll(env.a, removed.json()["job_id"]))["state"] == "completed"
    assert (await env.a.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 404
    assert (await env.b.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 200
    assert await vector_count(env) == count
    assert (await poll(env.a, await add(env.a)))["stage"] == "ready"
    assert env.captions.calls == [VIDEO_A]
    await env.a.delete(f"/api/videos/{VIDEO_A}")
    removed = await env.b.delete(f"/api/videos/{VIDEO_A}")
    deletion = removed.json()["job_id"]
    assert await env.worker.run_once(deletion)
    assert (await poll(env.b, deletion))["state"] == "completed"
    assert await vector_count(env) == 0
    new = await ready(env, env.b)
    assert env.repo.get_job(new, internal=True)["generation"] == 2
    assert env.captions.calls == [VIDEO_A, VIDEO_A]


@pytest.mark.parametrize("operation", ["get", "retry", "cancel"])
@pytest.mark.parametrize("admin", [False, True])
async def test_other_account_and_admin_cannot_access_private_job(members, operation, admin):
    env = members
    job = await add(env.a)
    if admin:
        with env.db.write() as c:
            c.execute(
                db.users.update()
                .where(db.users.c.user_id == env.user_b["user_id"])
                .values(role="admin")
            )
    path = f"/api/jobs/{job}" + ("" if operation == "get" else f"/{operation}")
    response = await env.b.request("GET" if operation == "get" else "POST", path)
    assert response.status_code == 404
    assert (await poll(env.a, job))["state"] == "queued"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/videos"),
        ("GET", f"/api/videos/{VIDEO_A}/transcript"),
        ("POST", "/api/videos/import"),
        ("DELETE", f"/api/videos/{VIDEO_A}"),
        ("GET", "/api/jobs/unknown"),
        ("POST", "/api/jobs/unknown/retry"),
        ("POST", "/api/jobs/unknown/cancel"),
    ],
)
async def test_native_routes_reject_missing_session(members, method, path):
    response = await members.guest.request(method, path, json={"urls": []})
    assert response.status_code == 401


@pytest.mark.parametrize("field", ["user_id", "owner_id", "role"])
async def test_import_rejects_client_ownership_fields(members, field):
    response = await members.a.post(
        "/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO_A}"], field: "forged"}
    )
    assert response.status_code == 422
    assert members.captions.calls == []


@pytest.mark.parametrize(
    "bad_header,value", [("X-CSRF-Token", "wrong"), ("Origin", "https://attacker.invalid")]
)
async def test_mutations_require_csrf_and_trusted_origin(members, bad_header, value):
    response = await members.a.post(
        "/api/videos/import",
        headers={bad_header: value},
        json={"urls": [f"https://youtu.be/{VIDEO_A}"]},
    )
    assert response.status_code == 403


async def test_shared_import_creator_detaches_during_fetch(members):
    env = members
    a, b = await add(env.a), await add(env.b)
    env.captions.delay = 0.2
    running = asyncio.create_task(env.worker.run_once(a))
    await asyncio.wait_for(env.captions.started.wait(), 5)
    # Native policy rejects cancellation of work still needed by B; detach is allowed.
    assert (await env.a.post(f"/api/jobs/{a}/cancel")).status_code == 409
    assert (await env.a.delete(f"/api/videos/{VIDEO_A}")).status_code == 202
    await running
    await env.worker.run_once(b)
    assert (await poll(env.b, b))["stage"] == "ready"
    assert (await env.b.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 200
    assert env.captions.calls == [VIDEO_A] and await vector_count(env) > 0


async def test_cancel_private_attach_preserves_other_members_import(members):
    env = members
    a, b = await add(env.a), await add(env.b)
    assert (await env.b.post(f"/api/jobs/{b}/cancel")).json()["state"] == "cancelled"
    await env.worker.run_once(a)
    assert (await poll(env.a, a))["stage"] == "ready"
    assert (await env.b.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 200
    assert env.captions.calls == [VIDEO_A]


async def test_private_retry_and_no_caption_classification(members, monkeypatch):
    env = members

    # Exhaust auto retries to exercise the real HTTP retry endpoint.
    async def unavailable(*args):
        raise AppError("ingest_unavailable", "Fixture outage", 503, True)

    monkeypatch.setattr(env.captions, "fetch", unavailable)
    job = await add(env.a)
    for _ in range(env.settings.job_max_attempts):
        await env.worker.run_once(job)
    assert (await poll(env.a, job))["state"] == "failed"
    assert (await env.b.post(f"/api/jobs/{job}/retry")).status_code == 404
    monkeypatch.setattr(env.captions, "fetch", Captions().fetch)
    retried = await env.a.post(f"/api/jobs/{job}/retry")
    assert retried.status_code == 202
    await env.worker.run_once(retried.json()["job_id"])
    assert (await poll(env.a, retried.json()["job_id"]))["stage"] == "ready"
    monkeypatch.setattr(env.captions, "fetch", env.captions.__class__().fetch)
    missing = await add(env.a, "NoCaption01")
    await env.worker.run_once(missing)
    result = await poll(env.a, missing)
    assert result["stage"] == "no_transcript" and not result["retryable"]
    assert (await env.a.post(f"/api/jobs/{missing}/retry")).status_code == 409


async def test_gc_waits_for_running_reader_and_revoked_reader_cannot_read(members):
    env = members
    await ready(env, env.a)
    # Enable admission only: this test manually claims the durable read job.
    env.adapters.capabilities = dict(env.adapters.capabilities, analyze=True)
    response = await env.a.post(
        "/api/analysis", json={"type": "summary", "scope": {"video_ids": [VIDEO_A]}}
    )
    assert response.status_code == 202, response.text
    job = env.repo.claim(response.json()["job_id"])
    context = ExecutionContext(
        env.repo, job["job_id"], job["lease_token"], job["deadline_at"], env.settings
    )
    sources = [Source.model_validate(s) for s in job["payload"]["sources"]]
    assert await env.adapters.inventory(sources, context) > 0
    removed = await env.a.delete(f"/api/videos/{VIDEO_A}")
    deletion = removed.json()["job_id"]
    count = await vector_count(env)
    assert not await env.worker.run_once(deletion)
    assert await vector_count(env) == count
    with pytest.raises(AppError):
        await env.adapters.inventory(sources, context)
    env.repo.fail(job["job_id"], job["lease_token"], AppError("cancelled", "Detached", 409))
    assert await env.worker.run_once(deletion)
    assert await vector_count(env) == 0


async def test_native_factory_needs_no_proposal_backend(members, monkeypatch):
    import youtube_ingestion.integration as module

    env = members
    assert not hasattr(env.repo, "member_ingestion_backend")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-2")
    monkeypatch.setattr(module, "RagAdapters", lambda **kwargs: env.adapters.knowledge)
    monkeypatch.setattr(module, "IngestionService", lambda *args: env.adapters.ingestion)
    adapters = await create_member_adapters(settings=env.settings, repository=env.repo)
    assert isinstance(adapters, IngestionAdapters)
    env.worker.adapters = adapters
    await ready(env, env.a, VIDEO_B)
    assert env.captions.calls == [VIDEO_B]


@pytest.mark.parametrize("admin", [False, True])
async def test_foreign_library_is_hidden_even_for_admin(members, admin):
    env = members
    await ready(env, env.a)
    if admin:
        with env.db.write() as c:
            c.execute(
                db.users.update()
                .where(db.users.c.user_id == env.user_b["user_id"])
                .values(role="admin")
            )
    assert (await env.b.get("/api/videos")).json()["items"] == []
    assert (await env.b.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 404
    assert (await env.b.delete(f"/api/videos/{VIDEO_A}")).status_code == 404
    assert (await env.a.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 200


async def test_native_batch_limit_is_enforced_before_admission(members):
    members.settings.import_max_urls = 1
    response = await members.a.post(
        "/api/videos/import",
        json={"urls": [f"https://youtu.be/{VIDEO_A}", f"https://youtu.be/{VIDEO_B}"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "import_limit"
    with members.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.user_videos)) == 0
        assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == 0
    assert members.captions.calls == []


async def test_member_factory_rejects_disabled_auth_before_clients(members, monkeypatch):
    import youtube_ingestion.member_adapters as module

    def forbidden(**kwargs):
        pytest.fail("Provider factory must not run")

    monkeypatch.setattr(module, "create_adapters", forbidden)
    with pytest.raises(AppError, match="native 02"):
        await create_member_adapters(
            settings=members.settings.model_copy(update={"auth_enabled": False}),
            repository=members.repo,
        )
