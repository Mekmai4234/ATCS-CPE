import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.fixture_adapter import FixtureAdapters
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.worker import Worker

VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "jNQXAC9IVRw"


@pytest.fixture(autouse=True)
def legacy_single_user_tests(request, monkeypatch):
    # Existing coordinator tests explicitly retain their single-user test environment.
    # New identity tests enable authentication on their Settings instance.
    if not request.module.__name__.endswith("test_identity"):
        monkeypatch.setenv("AUTH_ENABLED", "false")


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        adapter_mode="fixture",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        job_retry_base_seconds=0,
        # General integration work must not lose ownership under CI/browser load.
        # Lease expiry and heartbeat cases override the clock/lease explicitly.
        job_lease_seconds=30,
    )
    database = Database(settings.database_url)
    upgrade_database(database)
    repo = Repository(database, settings)
    adapters = FixtureAdapters(repo, settings)
    app = create_app(settings, database, adapters)
    worker = Worker(repo, adapters, settings)
    with TestClient(app) as client:
        yield SimpleNamespace(
            settings=settings,
            db=database,
            repo=repo,
            adapters=adapters,
            app=app,
            worker=worker,
            client=client,
        )


async def import_ready(env, *video_ids):
    items = env.repo.import_urls([f"https://youtu.be/{v}" for v in video_ids])
    for item in items:
        await env.worker.run_once(item["job_id"])
        assert env.repo.get_job(item["job_id"])["stage"] == "ready"
    return items


@pytest.fixture
def ready(env):
    asyncio.run(import_ready(env, VIDEO_A, VIDEO_B))
    return env


def chat_body(*video_ids, question="RAG คืออะไร", **extra):
    return dict(question=question, scope={"video_ids": list(video_ids or [VIDEO_A])}, **extra)
