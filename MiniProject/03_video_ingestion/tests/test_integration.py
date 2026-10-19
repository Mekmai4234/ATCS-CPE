import asyncio
from types import SimpleNamespace

import httpx
import pytest
from conftest import VIDEO_A, VIDEO_B, track
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import initialize

from youtube_ingestion.integration import IngestionAdapters, create_adapters
from youtube_ingestion.models import Metadata
from youtube_ingestion.service import IngestionService


class Captions:
    def __init__(self):
        self.calls = []
        self.delay = 0
        self.started = asyncio.Event()
        self.stopped = False

    async def fetch(self, video_id, languages, timeout):
        self.calls.append(video_id)
        self.started.set()
        try:
            await asyncio.sleep(self.delay)
            if video_id == "NoCaption01":
                raise AppError("no_transcript", "No captions", 409)
            if video_id == "RetryOnce01" and self.calls.count(video_id) == 1:
                raise AppError("ingest_unavailable", "Temporary transport failure", 503, True)
            return track(video_id)
        finally:
            self.stopped = True

    async def close(self):
        pass


class Meta:
    async def fetch(self, video_id, timeout):
        return Metadata(title="[FIXTURE] lesson", channel_id="channel-a", published_at="2026-01-01")

    async def close(self):
        pass


@pytest.fixture
async def integrated(tmp_path, config):
    settings = Settings(
        _env_file=None,
        app_env="test",
        adapter_mode="custom",
        adapter_factory="youtube_ingestion.integration:create_adapters",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        job_lease_seconds=30,
        job_timeout_seconds=60,
        job_retry_base_seconds=0,
    )
    database = Database(settings.database_url)
    upgrade_database(database)
    initialize(database)
    repository = Repository(database, settings)
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
        repository=repository,
        rag_settings=rag_config,
        embedder=FixtureEmbedder(rag_config),
    )
    captions = Captions()
    ingestion = IngestionService(config, captions=captions, metadata=Meta())
    adapters = IngestionAdapters(ingestion, knowledge)
    app = create_app(settings, database, adapters)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield SimpleNamespace(
                settings=settings,
                db=database,
                repo=app.state.repository,
                worker=app.state.worker,
                client=client,
                adapters=adapters,
                captions=captions,
                config=rag_config,
            )


async def enqueue(env, video_id):
    response = await env.client.post(
        "/api/videos/import", json={"urls": [f"https://youtu.be/{video_id}"]}
    )
    assert response.status_code == 202, response.text
    return response.json()["jobs"][0]["job_id"]


async def test_http_worker_transcript_real_chroma_reopen_and_delete(integrated):
    env = integrated
    health = (await env.client.get("/health")).json()
    assert health["capabilities"]["ingest"] == "available"
    assert health["capabilities"]["answer"] == "unavailable"
    assert (
        await env.client.post(
            "/api/chat", json={"question": "RAG", "scope": {"video_ids": [VIDEO_A]}}
        )
    ).status_code == 503
    first = await enqueue(env, VIDEO_A)
    assert (await env.client.get(f"/api/jobs/{first}")).json()["state"] == "queued"
    await env.worker.run_once(first)
    job = env.repo.get_job(first)
    assert job["stage"] == "ready" and job["result"]["chunk_count"] > 0
    response = await env.client.get(f"/api/videos/{VIDEO_A}/transcript")
    assert response.status_code == 200
    assert response.json()["segments"][1]["start_seconds"] == 12
    assert response.json()["source"] == "youtube_captions:manual"
    assert await enqueue(env, VIDEO_A) == first
    assert env.captions.calls == [VIDEO_A]
    await env.adapters.knowledge.close()
    other_db = Database(env.settings.database_url)
    other = RagAdapters(
        settings=env.settings,
        repository=Repository(other_db, env.settings),
        rag_settings=env.config,
        embedder=FixtureEmbedder(env.config),
    )
    try:
        assert await other.rag.vectors.call("count", 15) == job["result"]["chunk_count"]
        # The persisted publication manifest and actual Chroma vector count survive reopening.
        from youtube_ingestion.integration import IngestionAdapters

        env.worker.adapters = IngestionAdapters(env.adapters.ingestion, other)
        deletion = await env.client.delete(f"/api/videos/{VIDEO_A}")
        delete_id = deletion.json()["job_id"]
        await env.worker.run_once(delete_id)
        assert env.repo.get_job(delete_id)["state"] == "completed"
        assert (await env.client.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 404
        assert await other.rag.vectors.call("count", 15) == 0
        second = await enqueue(env, VIDEO_A)
        await env.worker.run_once(second)
        assert env.repo.get_job(second)["stage"] == "ready"
        assert env.repo.get_job(second)["generation"] == 2
    finally:
        await other.close()
        other_db.close()


async def test_batch_missing_captions_retry_and_invalid_url(integrated):
    env = integrated
    response = await env.client.post(
        "/api/videos/import",
        json={
            "urls": [
                f"https://youtu.be/{VIDEO_A}",
                "https://youtu.be/NoCaption01",
                "https://youtu.be/RetryOnce01",
                "https://evil.example/watch?v=" + VIDEO_A,
            ]
        },
    )
    items = response.json()["jobs"]
    assert items[3]["outcome"] == "rejected"
    for item in items[:3]:
        await env.worker.run_once(item["job_id"])
    assert env.repo.get_job(items[0]["job_id"])["stage"] == "ready"
    no_captions = env.repo.get_job(items[1]["job_id"])
    assert no_captions["stage"] == "no_transcript" and not no_captions["retryable"]
    transient = env.repo.get_job(items[2]["job_id"])
    assert transient["state"] == "queued" and transient["attempt_count"] == 1
    await env.worker.run_once(transient["job_id"])
    final = env.repo.get_job(transient["job_id"])
    assert final["stage"] == "ready" and final["attempt_count"] == 2
    assert env.repo.transcript(VIDEO_A, 100, 0)["total"] == 2


@pytest.mark.parametrize("delete", [False, True])
async def test_cancel_or_delete_during_fetch_cannot_publish(integrated, delete):
    env = integrated
    env.captions.delay = 30
    job_id = await enqueue(env, VIDEO_A)
    running = asyncio.create_task(env.worker.run_once(job_id))
    await asyncio.wait_for(env.captions.started.wait(), 5)
    if delete:
        await env.client.delete(f"/api/videos/{VIDEO_A}")
    else:
        await env.client.post(f"/api/jobs/{job_id}/cancel")
    await asyncio.wait_for(running, 5)
    assert env.repo.get_job(job_id)["state"] == "cancelled"
    assert env.captions.stopped
    assert await env.adapters.knowledge.rag.vectors.call("count", 15) == 0


async def test_invalid_caption_intervals_fail_before_indexing(integrated, monkeypatch):
    async def bad(*args):
        result = track()
        result["segments"][0]["duration"] = -1
        return result

    env = integrated
    monkeypatch.setattr(env.captions, "fetch", bad)
    job_id = await enqueue(env, VIDEO_A)
    await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "failed" and job["error_code"] == "invalid_transcript"
    assert await env.adapters.knowledge.rag.vectors.call("count", 15) == 0


async def test_index_failure_never_marks_video_ready(integrated, monkeypatch):
    async def bad(*args):
        raise AppError("incomplete_index", "Simulated index failure", 502)

    env = integrated
    monkeypatch.setattr(env.adapters, "index", bad)
    job_id = await enqueue(env, VIDEO_B)
    await env.worker.run_once(job_id)
    assert env.repo.get_job(job_id)["state"] == "failed"
    assert env.repo.list_videos(100, 0)["items"][0]["status"] == "failed"


async def test_production_factory_rejects_offline_profile(integrated):
    env = integrated
    settings = env.settings.model_copy(update={"backend_integration_profile": "offline"})
    with pytest.raises(AppError) as error:
        await create_adapters(settings=settings, repository=env.repo)
    assert error.value.code == "ingestion_configuration"


async def test_factory_owns_and_closes_live_clients_without_provider_calls(integrated, monkeypatch):
    env = integrated
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-real-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-2")
    adapters = await create_adapters(settings=env.settings, repository=env.repo)
    await adapters.close()
    await adapters.close()
    assert adapters.ingestion.closed
    assert adapters.knowledge.rag.embedder._http_client.is_closed


async def test_factory_startup_failure_closes_rag(integrated, monkeypatch):
    import youtube_ingestion.integration as module

    closed = []

    class Knowledge:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            closed.append(True)

    def bad(*args):
        raise RuntimeError("setup failed")

    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-2")
    monkeypatch.setattr(module, "RagAdapters", Knowledge)
    monkeypatch.setattr(module, "IngestionService", bad)
    with pytest.raises(RuntimeError):
        await create_adapters(settings=integrated.settings, repository=integrated.repo)
    assert closed == [True]
