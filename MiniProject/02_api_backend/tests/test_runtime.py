import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from youtube_backend import runtime as runtime_module
from youtube_backend.cli import run_worker
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.main import create_app
from youtube_backend.repository import Repository
from youtube_backend.runtime import ManagedAdapters


async def test_concurrent_lazy_start_constructs_and_closes_once(env, monkeypatch):
    constructed, closed = [], []

    async def factory(*args):
        constructed.append(True)
        await asyncio.sleep(0)

        async def close():
            closed.append(True)

        return SimpleNamespace(close=close)

    monkeypatch.setattr(runtime_module, "load_adapters", factory)
    managed = ManagedAdapters(env.settings, env.repo)
    await asyncio.gather(*(managed.start() for _ in range(8)))
    assert len(constructed) == 1
    await managed.close()
    await managed.close()
    assert len(closed) == 1
    with pytest.raises(AppError, match="stopped"):
        await managed.start()


async def test_close_waits_for_inflight_start_and_cleans_constructed_resource(env, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    closed = []

    async def close():
        closed.append(True)

    async def factory(*args):
        entered.set()
        await release.wait()
        return SimpleNamespace(close=close)

    monkeypatch.setattr(runtime_module, "load_adapters", factory)
    managed = ManagedAdapters(env.settings, env.repo)
    start = asyncio.create_task(managed.start())
    await entered.wait()
    cleanup = asyncio.create_task(managed.close())
    release.set()
    await asyncio.gather(start, cleanup)
    assert closed == [True]


def test_integration_environment_precedence_is_explicit(tmp_path, monkeypatch):
    shared, integration = tmp_path / "shared.env", tmp_path / "integration.env"
    shared.write_text("AGENT_MAX_STEPS=3\n", encoding="utf-8")
    integration.write_text("AGENT_MAX_STEPS=5\n", encoding="utf-8")
    monkeypatch.delenv("AGENT_MAX_STEPS", raising=False)
    assert Settings(_env_file=(shared, integration)).agent_max_steps == 5
    monkeypatch.setenv("AGENT_MAX_STEPS", "7")
    assert Settings(_env_file=(shared, integration)).agent_max_steps == 7


def test_api_constructs_adapters_only_inside_lifespan_and_closes_on_exit(env, monkeypatch):
    calls = []

    class Adapter:
        async def close(self):
            calls.append("close")

    def factory(*args):
        calls.append("construct")
        return Adapter()

    monkeypatch.setattr(runtime_module, "load_adapters", factory)
    app = create_app(env.settings, env.db)
    assert calls == []
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert calls == ["construct"]
    assert calls == ["construct", "close"]


def test_missing_schema_prevents_adapter_construction(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None, database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    )
    calls = []
    monkeypatch.setattr(runtime_module, "load_adapters", lambda *args: calls.append(True))
    with pytest.raises(RuntimeError, match="schema"), TestClient(create_app(settings)):
        pass
    assert not calls


async def test_worker_closes_adapter_after_once_and_after_cancellation(env, monkeypatch):
    closed = []

    class Adapter:
        async def close(self):
            closed.append(True)

    monkeypatch.setattr(runtime_module, "load_adapters", lambda *args: Adapter())
    await run_worker(env.settings, env.db, once=True)
    assert closed == [True]
    running = asyncio.create_task(run_worker(env.settings, env.db))
    await asyncio.sleep(0.03)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert closed == [True, True]


def test_unavailable_operations_fail_before_creating_jobs(env):
    settings = env.settings.model_copy(update={"adapter_mode": "unavailable"})
    app = create_app(settings, env.db)
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["capabilities"]["ingest"] == "unavailable"
        assert not health["live_provider_verified"]
        for path, body in [
            ("/api/videos/import", {"urls": ["https://youtu.be/dQw4w9WgXcQ"]}),
            ("/api/chat", {"question": "RAG", "scope": {"video_ids": ["dQw4w9WgXcQ"]}}),
        ]:
            response = client.post(path, json=body)
            assert response.status_code == 503
            assert not response.json()["error"]["retryable"]
        assert client.get("/api/videos").json()["total"] == 0


def test_custom_profile_cannot_relabel_an_existing_database(env):
    settings = env.settings.model_copy(
        update={
            "adapter_mode": "custom",
            "adapter_factory": "example:create",
            "backend_integration_profile": "offline",
        }
    )
    repo = Repository(env.db, settings)
    repo.import_urls(["https://youtu.be/dQw4w9WgXcQ"])
    settings.backend_integration_profile = "live"
    with pytest.raises(AppError, match="separate DATABASE_URL"):
        repo.check_mode()


def test_offline_profile_is_not_allowed_in_production():
    with pytest.raises(ValueError, match="development/test"):
        Settings(_env_file=None, app_env="production", backend_integration_profile="offline")


async def test_database_closed_even_if_adapter_close_fails(env, monkeypatch):
    calls = []

    class BadClose:
        async def close(self):
            raise RuntimeError("close failed")

    database = Database(env.settings.database_url)
    original = database.close

    def close():
        calls.append(True)
        original()

    monkeypatch.setattr(database, "close", close)
    app = create_app(env.settings, database, BadClose())
    with pytest.raises(RuntimeError, match="close failed"):
        async with app.router.lifespan_context(app):
            pass
    assert calls == [True]
