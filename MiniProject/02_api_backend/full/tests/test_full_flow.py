"""Real full factory, 03 normalization, 04 Chroma, 05 service and 02 API/worker.

Only external captions/metadata, embeddings and model calls are labelled doubles.
No delivery runtime flag enables these doubles; they exist only in the test image.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic_settings import DotEnvSettingsSource
from youtube_agent.models import ModelReply
from youtube_answers.models import Generated, GeneratedAnswer
from youtube_ingestion.models import CaptionTrack, Metadata, RawSegment
from youtube_rag.embeddings import FixtureEmbedder

from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.full import FullSettings
from youtube_backend.full_pair import check_pair, initialize_pair
from youtube_backend.main import create_app
from youtube_backend.repository import Repository
from youtube_backend.runtime import ManagedAdapters
from youtube_backend.schemas import ProviderMetadata
from youtube_backend.worker import Worker

VIDEO_A, VIDEO_B = "dQw4w9WgXcQ", "jNQXAC9IVRw"


def assert_resolved_settings(adapters, settings):
    actual = {
        "answer": adapters.answers.answers.settings,
        "rag": adapters.answers.rag.settings,
        "ingestion": adapters.ingestion.settings,
        "agent": adapters.agent.settings,
    }
    for name, expected in settings.services().items():
        assert actual[name].model_dump() == expected.model_dump(), name


def hostile_module_dotenv(monkeypatch, settings, file):
    """Exercise each service's settings sources without touching a private 05 constant.

    Preserve explicit `_env_file=None`. When dotenv is enabled (older 05), replace
    its files with the hostile temporary file, never reading a user's real dotenv.
    The new resolved-settings loader must also pass the actual-value assertions.
    """
    for service in settings.services().values():
        cls = type(service)
        monkeypatch.setitem(cls.model_config, "env_file", (file,))

        def sources(
            settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        ):
            dotenv = DotEnvSettingsSource(
                settings_cls,
                env_file=None if dotenv_settings.env_file is None else file,
                env_file_encoding="utf-8",
            )
            return init_settings, env_settings, dotenv, file_secret_settings

        monkeypatch.setattr(cls, "settings_customise_sources", staticmethod(sources))


def metadata():
    return ProviderMetadata(
        provider="fixture",
        requested_model="fixture",
        returned_model="fixture-full-test",
        usage={},
        latency_ms=1,
    )


class ModelDouble:
    def __init__(self, settings):
        self.settings = settings

    async def generate(self, payload, timeout):
        refs = list(
            dict.fromkeys(c for item in payload["untrusted_evidence"] for c in item["citation_ids"])
        )
        return Generated(
            GeneratedAnswer.model_validate(
                {
                    "status": "answered",
                    "statements": [
                        {"text": "[FIXTURE] RAG retrieves evidence.", "citation_ids": refs}
                    ],
                }
            ),
            metadata(),
        )

    async def decide(self, history, timeout):
        observations = [item for item in history if item["role"] == "tool"]
        if not observations:
            return ModelReply("compare_videos", {"video_ids": [VIDEO_A, VIDEO_B]}, metadata())
        return ModelReply(
            "finish_research",
            {
                "content": "[FIXTURE] Compared evidence.",
                "citation_ids": [
                    item["chunk_id"] for item in observations[-1]["result"]["evidence"]
                ],
            },
            metadata(),
        )

    async def close(self):
        pass


def install_doubles(monkeypatch):
    from youtube_agent import gemini
    from youtube_answers import team
    from youtube_ingestion.captions import SubprocessCaptions
    from youtube_ingestion.metadata import YouTubeMetadata
    from youtube_rag import integration

    async def captions(self, video_id, languages, timeout):
        return CaptionTrack(
            video_id=video_id,
            language="en",
            is_generated=False,
            segments=[
                RawSegment(
                    text="[FIXTURE] RAG retrieves evidence before answering.",
                    start=0.0,
                    duration=10.0,
                ),
                RawSegment(
                    text="[FIXTURE] Answers cite the supplied source evidence.",
                    start=10.0,
                    duration=10.0,
                ),
            ],
        )

    async def title(self, video_id, timeout):
        return Metadata(title=f"[FIXTURE] {video_id}")

    class HashDouble(FixtureEmbedder):
        def __init__(self, settings):
            # Test-only transport substitute preserves the requested config contract.
            # Its vectors exist only in pytest's temporary directory, never demo/live data.
            self.settings = settings

    monkeypatch.setattr(team, "GeminiModel", ModelDouble)
    monkeypatch.setattr(gemini, "GeminiModel", ModelDouble)
    monkeypatch.setattr(integration, "GeminiEmbedder", HashDouble)
    monkeypatch.setattr(SubprocessCaptions, "fetch", captions)
    monkeypatch.setattr(YouTubeMetadata, "fetch", title)


@pytest.fixture
async def full(tmp_path, monkeypatch, request):
    settings = FullSettings(
        _env_file=None,
        app_env="test",
        auth_enabled=getattr(request, "param", False),
        google_client_id="fixture-client",
        session_cookie_secure=False,
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        chroma_persist_dir=str(tmp_path / "chroma"),
        gemini_api_key="test-only-not-a-real-key",
        job_retry_base_seconds=0,
        job_lease_seconds=120,
        transcript_languages="en,th",
        metadata_provider="none",
        ingest_timeout_seconds=25,
        answer_read_page_size=75,
        answer_max_history_bytes=4321,
        agent_max_steps=7,
        retrieval_top_k=5,
    )
    initialize_pair(settings)
    for key, value in settings.child_environment({}).items():
        monkeypatch.setenv(key, value)
    file = tmp_path / "module.env"
    file.write_text(
        "CHROMA_PERSIST_DIR=wrong\nLLM_MODEL=wrong\nGEMINI_API_KEY=wrong\n"
        "TRANSCRIPT_LANGUAGES=fr\nMETADATA_PROVIDER=oembed\nINGEST_TIMEOUT_SECONDS=99\n"
        "ANSWER_READ_PAGE_SIZE=10\nANSWER_MAX_HISTORY_BYTES=100\nAGENT_MAX_STEPS=2\n"
        "RETRIEVAL_TOP_K=1\n",
        encoding="utf-8",
    )
    hostile_module_dotenv(monkeypatch, settings, file)
    install_doubles(monkeypatch)
    # Match the real child entrypoints: only shared backend fields are on Settings;
    # 03/05-specific fields must survive through the launcher's exported environment.
    runtime_settings = Settings(_env_file=None)
    database = Database(settings.database_url)
    repo = Repository(database, runtime_settings)
    runtime = ManagedAdapters(runtime_settings, repo)
    try:
        await runtime.start()
        assert_resolved_settings(runtime.adapter, settings)
    except BaseException:
        await runtime.close()
        database.close()
        raise
    app = create_app(runtime_settings, database, runtime.adapter)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            yield SimpleNamespace(
                settings=settings,
                app=app,
                runtime_settings=runtime_settings,
                db=database,
                repo=repo,
                runtime=runtime,
                client=c,
                worker=Worker(repo, runtime, runtime_settings),
            )
    finally:
        await runtime.close()
        database.close()


async def import_ready(env):
    response = await env.client.post(
        "/api/videos/import",
        json={"urls": [f"https://youtu.be/{VIDEO_A}", f"https://youtu.be/{VIDEO_B}"]},
    )
    assert response.status_code == 202, response.text
    for item in response.json()["jobs"]:
        await env.worker.run_once(item["job_id"])
        job = env.repo.get_job(item["job_id"])
        assert job["stage"] == "ready", job


async def test_full_factory_import_chat_analysis_research_and_reopen(full):
    env = full
    await import_ready(env)
    health = (await env.client.get("/health")).json()
    assert set(health["capabilities"].values()) == {"available"}
    assert health["full_pair_preflight"] and not health["live_provider_verified"]
    adapters = env.runtime.adapter
    assert adapters.answers.rag is adapters.agent.knowledge.rag
    assert str(adapters.answers.rag.settings.chroma_persist_dir) == env.settings.chroma_persist_dir
    body = {"question": "What does RAG retrieve?", "scope": {"video_ids": [VIDEO_A]}}
    headers = {"Idempotency-Key": "full-test-chat"}
    answer = await env.client.post("/api/chat", json=body, headers=headers)
    assert answer.status_code in {200, 202}, answer.text
    job_id = answer.json()["job_id"]
    if answer.status_code == 202:
        await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "completed", job
    assert job["result"]["citations"]
    assert job["result"]["provider_metadata"]["provider"] == "fixture"
    replay = await env.client.post("/api/chat", json=body, headers=headers)
    assert replay.json()["job_id"] == job_id
    history = await env.client.get(f"/api/conversations/{job['conversation_id']}")
    assert len(history.json()["messages"]) == 2
    scope = {"video_ids": [VIDEO_A, VIDEO_B]}
    for kind in ("summary", "compare"):
        accepted = await env.client.post("/api/analysis", json={"type": kind, "scope": scope})
        assert accepted.status_code == 202
        analysis_id = accepted.json()["job_id"]
        await env.worker.run_once(analysis_id)
        assert env.repo.get_job(analysis_id)["state"] == "completed"
    research = await env.client.post("/api/research", json={"goal": "Compare RAG", "scope": scope})
    await env.worker.run_once(research.json()["job_id"])
    assert env.repo.get_job(research.json()["job_id"])["state"] == "completed"
    await env.runtime.close()
    restarted = ManagedAdapters(env.runtime_settings, env.repo)
    try:
        await restarted.start()
        assert_resolved_settings(restarted.adapter, env.settings)
        assert env.repo.get_job(job_id)["result"] == job["result"]
        assert check_pair(env.settings)
        deletion = await env.client.delete(f"/api/videos/{VIDEO_A}")
        await Worker(env.repo, restarted, env.settings).run_once(deletion.json()["job_id"])
        assert env.repo.get_job(deletion.json()["job_id"])["state"] == "completed"
        assert (await env.client.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 404
    finally:
        await restarted.close()


@pytest.mark.parametrize("action", ["cancel", "delete"])
async def test_full_analysis_cannot_publish_after_cancel_or_delete(full, monkeypatch, action):
    await import_ready(full)
    started, proceed = asyncio.Event(), asyncio.Event()
    original = ModelDouble.generate

    async def slow(self, payload, timeout):
        started.set()
        await proceed.wait()
        return await original(self, payload, timeout)

    monkeypatch.setattr(ModelDouble, "generate", slow)
    accepted = await full.client.post(
        "/api/analysis", json={"type": "summary", "scope": {"video_ids": [VIDEO_A]}}
    )
    job_id = accepted.json()["job_id"]
    running = asyncio.create_task(full.worker.run_once(job_id))
    try:
        await asyncio.wait_for(started.wait(), 15)
        if action == "cancel":
            assert (await full.client.post(f"/api/jobs/{job_id}/cancel")).status_code == 200
        else:
            assert (await full.client.delete(f"/api/videos/{VIDEO_A}")).status_code == 202
        proceed.set()
        await asyncio.wait_for(running, 15)
        job = full.repo.get_job(job_id)
        assert job["state"] == "cancelled", job
        assert job["result"] is None
    finally:
        proceed.set()
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("full", [True], indirect=True)
async def test_authenticated_accounts_share_real_rag_without_cross_account_access(full):
    import time

    async def sign_in(client, subject):
        challenge = (await client.get("/api/auth/challenge")).json()
        full.app.state.auth.verifier = lambda credential, audience: dict(
            sub=subject,
            aud=audience,
            iss="https://accounts.google.com",
            exp=time.time() + 300,
            nonce=challenge["nonce"],
            name=f"[FIXTURE] {subject}",
        )
        result = await client.post(
            "/api/auth/google",
            headers={"Origin": "http://localhost:3000"},
            json={"credential": "fixture-credential", "csrf_token": challenge["csrf_token"]},
        )
        assert result.status_code == 200, result.text
        client.headers.update(
            {"Origin": "http://localhost:3000", "X-CSRF-Token": result.json()["csrf_token"]}
        )

    a = full.client
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(full.app), base_url="http://test"
    ) as b:
        await sign_in(a, "a")
        await sign_in(b, "b")
        data = {"urls": [f"https://youtu.be/{VIDEO_A}"]}
        first = (await a.post("/api/videos/import", json=data)).json()["jobs"][0]["job_id"]
        await full.worker.run_once(first)
        assert (await a.get(f"/api/jobs/{first}")).json()["stage"] == "ready"
        assert (await b.get(f"/api/jobs/{first}")).status_code == 404
        assert (await b.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 404
        request_body = {"question": "RAG", "scope": {"video_ids": [VIDEO_A]}}
        assert (await b.post("/api/chat", json=request_body)).status_code == 404
        second = (await b.post("/api/videos/import", json=data)).json()["jobs"][0]["job_id"]
        assert second != first
        response = await b.post("/api/chat", json=request_body)
        assert response.status_code == 200, response.text
        assert response.json()["citations"]
        conversation_id = response.json()["conversation_id"]
        assert (await a.get(f"/api/conversations/{conversation_id}")).status_code == 404
        await a.delete(f"/api/videos/{VIDEO_A}")
        assert (await a.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 404
        assert (await b.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 200
        deleted = (await b.delete(f"/api/videos/{VIDEO_A}")).json()["job_id"]
        await full.worker.run_once(deleted)
        assert (await b.get(f"/api/jobs/{deleted}")).json()["state"] == "completed"
        assert await full.runtime.adapter.answers.rag.vectors.call("count", 10) == 0


async def test_legacy_migration_preserves_actual_sqlite_chroma_pair(full, tmp_path):
    from pathlib import Path

    import sqlalchemy as sa
    from alembic import command
    from youtube_rag.vectors import ChromaStore

    from youtube_backend import database as tables
    from youtube_backend.auth_cli import paired_backup
    from youtube_backend.migration import alembic_config, upgrade_database

    await import_ready(full)
    pending = full.repo.enqueue("analysis", {"type": "summary", "scope": {"video_ids": [VIDEO_A]}})
    original = check_pair(full.settings)
    marker_path = Path(full.settings.chroma_persist_dir) / ".yk04-store.json"
    marker = marker_path.read_bytes()
    await full.runtime.close()  # stop actual Chroma subprocess before paired backup
    with full.db.engine.begin() as connection:
        command.downgrade(alembic_config(connection), "0001")
    backup = tmp_path / "paired-backup"
    paired_backup(full.settings, backup)
    upgrade_database(full.db, allow_legacy=True)
    assert check_pair(full.settings) == original
    assert marker_path.read_bytes() == marker == (backup / "chroma/.yk04-store.json").read_bytes()
    with full.db.read() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(tables.legacy_sources)) == 2
        assert connection.scalar(sa.select(sa.func.count()).select_from(tables.user_videos)) == 0
        job = (
            connection.execute(
                sa.select(tables.jobs).where(tables.jobs.c.job_id == pending["job_id"])
            )
            .mappings()
            .one()
        )
        assert job["state"] == "cancelled" and job["error_code"] == "legacy_owner_required"
        assert job["owner_id"] is None
    store = ChromaStore(
        Path(full.settings.chroma_persist_dir), full.settings.services()["rag"].collection_name
    )
    try:
        assert await store.call("count", 15) > 0
    finally:
        await store.close()
