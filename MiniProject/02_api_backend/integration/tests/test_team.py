import asyncio
from types import SimpleNamespace

import httpx
import pytest
from youtube_rag.manifest import initialize

from youtube_backend.cli import seed_offline
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.team import create_adapters

VIDEO_A, VIDEO_B = "dQw4w9WgXcQ", "jNQXAC9IVRw"


@pytest.fixture
async def integrated(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=False,
        adapter_mode="custom",
        adapter_factory="youtube_backend.team:create_adapters",
        backend_integration_profile="offline",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        chroma_persist_dir=str(tmp_path / "chroma"),
        gemini_api_key="",
        job_lease_seconds=30,
        job_retry_base_seconds=0,
    )
    database = Database(settings.database_url)
    upgrade_database(database)
    initialize(database)
    await seed_offline(settings, database, [VIDEO_A, VIDEO_B])
    app = create_app(settings, database)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield SimpleNamespace(
                settings=settings,
                db=database,
                app=app,
                client=client,
                repo=app.state.repository,
                worker=app.state.worker,
                adapters=app.state.adapters.adapter,
            )


async def run_task(env, path, body):
    response = await env.client.post(path, json=body)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] in {"completed", "partial"}, job
    return job


async def test_real_rag_and_agent_through_api_and_factory(integrated):
    env = integrated
    health = (await env.client.get("/health")).json()
    assert health["integration_profile"] == "offline" and health["synthetic_data"]
    assert health["capabilities"]["research"] == "available"
    assert health["capabilities"]["answer"] == "unavailable"
    assert health["capabilities"]["ingest"] == "unavailable"
    for path, body in [
        ("/api/videos/import", {"urls": [f"https://youtu.be/{VIDEO_A}"]}),
        ("/api/chat", {"question": "RAG", "scope": {"video_ids": [VIDEO_A]}}),
        ("/api/analysis", {"type": "summary", "scope": {"video_ids": [VIDEO_A]}}),
    ]:
        assert (await env.client.post(path, json=body)).status_code == 503
    for kind in ("study_plan", "quiz", "flashcards"):
        job = await run_task(
            env,
            "/api/learning-artifacts",
            {
                "type": kind,
                "scope": {"video_ids": [VIDEO_A]},
                "days": 3,
            },
        )
        assert job["result"]["provider_metadata"]["provider"] == "fixture"
        artifact = env.repo.artifact(job["result"]["artifact_ids"][0])
        assert artifact["sources_available"] and artifact["type"] == kind
    job = await run_task(
        env,
        "/api/research",
        {
            "goal": "Study RAG",
            "scope": {"video_ids": [VIDEO_A, VIDEO_B]},
            "days": 3,
        },
    )
    assert job["state"] == "completed"
    assert job["result"]["coverage"]["complete"]
    assert {e["tool_name"] for e in env.repo.list_events(job["job_id"])} >= {
        "read_video_chunks",
        "create_learning_artifact",
    }


async def test_same_budgets_from_backend_and_no_module_env_divergence(integrated):
    env = integrated
    assert env.adapters.agent.settings.agent_timeout_seconds == env.settings.agent_timeout_seconds
    assert env.adapters.agent.settings.agent_max_steps == env.settings.agent_max_steps
    assert (
        env.adapters.agent.settings.agent_finalize_reserve_seconds
        == env.settings.agent_finalize_reserve_seconds
    )
    assert env.adapters.knowledge.rag.settings.embedding_provider == "fixture"
    assert env.adapters.knowledge.rag.settings.chroma_persist_dir.is_absolute()


async def test_delete_cleans_real_chroma_and_saved_artifact_flags(integrated):
    env = integrated
    job = await run_task(
        env,
        "/api/learning-artifacts",
        {
            "type": "quiz",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    artifact_id = job["result"]["artifact_ids"][0]
    response = await env.client.delete(f"/api/videos/{VIDEO_A}")
    await env.worker.run_once(response.json()["job_id"])
    assert env.repo.get_job(response.json()["job_id"])["state"] == "completed"
    assert not env.repo.artifact(artifact_id)["sources_available"]
    assert (await env.client.get(f"/api/videos/{VIDEO_A}/transcript")).status_code == 404


async def test_cancellation_and_source_deletion_prevent_results(integrated):
    env = integrated
    started = asyncio.Event()
    original = env.adapters.agent.model.decide

    async def delayed(*args):
        started.set()
        await asyncio.sleep(0.1)
        return await original(*args)

    env.adapters.agent.model.decide = delayed
    response = await env.client.post(
        "/api/research",
        json={
            "goal": "Study",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    job_id = response.json()["job_id"]
    running = asyncio.create_task(env.worker.run_once(job_id))
    await asyncio.wait_for(started.wait(), 15)
    await env.client.post(f"/api/research/{job_id}/cancel")
    await running
    assert env.repo.get_job(job_id)["state"] == "cancelled"
    assert env.repo.get_job(job_id)["result"] is None
    started.clear()
    response = await env.client.post(
        "/api/research",
        json={
            "goal": "Study",
            "scope": {"video_ids": [VIDEO_B]},
        },
    )
    job_id = response.json()["job_id"]
    running = asyncio.create_task(env.worker.run_once(job_id))
    await asyncio.wait_for(started.wait(), 15)
    await env.client.delete(f"/api/videos/{VIDEO_B}")
    await running
    assert env.repo.get_job(job_id)["state"] == "cancelled"


async def test_restart_reopens_same_vectors_and_results(integrated):
    env = integrated
    job = await run_task(
        env,
        "/api/learning-artifacts",
        {
            "type": "flashcards",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    await env.app.state.adapters.close()
    assert env.adapters.agent.model.closed
    other_db = Database(env.settings.database_url)
    other_repo = Repository(other_db, env.settings)
    other = await create_adapters(settings=env.settings, repository=other_repo)
    try:
        assert other_repo.get_job(job["job_id"])["result"] == job["result"]
        assert other_repo.artifact(job["result"]["artifact_ids"][0])["sources_available"]
    finally:
        await other.close()
        other_db.close()


async def test_live_profile_requires_key_without_calling_a_provider(integrated):
    settings = integrated.settings.model_copy(update={"backend_integration_profile": "live"})
    with pytest.raises(AppError) as error:
        await create_adapters(settings=settings, repository=integrated.repo)
    assert error.value.code == "generation_unavailable"


async def test_seed_cannot_put_synthetic_transcripts_into_live_profile(integrated):
    settings = integrated.settings.model_copy(update={"backend_integration_profile": "live"})
    with pytest.raises(AppError) as error:
        await seed_offline(settings, integrated.db, ["AnotherId01"])
    assert error.value.code == "fixture_forbidden"
    assert integrated.repo.list_videos(100, 0)["total"] == 2


async def test_agent_budget_returns_partial_and_retains_progress(integrated):
    env = integrated
    env.adapters.agent.settings.agent_max_steps = 1
    response = await env.client.post(
        "/api/research",
        json={
            "goal": "Learn",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    job_id = response.json()["job_id"]
    await env.worker.run_once(job_id)
    result = env.repo.get_job(job_id)
    assert result["state"] == "partial"
    assert not result["result"]["coverage"]["complete"]
    assert env.repo.list_events(job_id)


async def test_failed_team_start_closes_both_model_and_knowledge(integrated, monkeypatch):
    import youtube_agent.service
    import youtube_rag.integration

    import youtube_backend.offline_model

    calls = []

    class Knowledge:
        def __init__(self, **kwargs):
            self.rag = None

        async def close(self):
            calls.append("knowledge")

    class Model:
        def __init__(self, *args):
            pass

        async def close(self):
            calls.append("model")

    def bad_agent(*args):
        raise RuntimeError("setup failed")

    monkeypatch.setattr(youtube_rag.integration, "RagAdapters", Knowledge)
    monkeypatch.setattr(youtube_backend.offline_model, "OfflineModel", Model)
    monkeypatch.setattr(youtube_agent.service, "AgentService", bad_agent)
    with pytest.raises(RuntimeError, match="setup failed"):
        await create_adapters(settings=integrated.settings, repository=integrated.repo)
    assert calls == ["model", "knowledge"]
