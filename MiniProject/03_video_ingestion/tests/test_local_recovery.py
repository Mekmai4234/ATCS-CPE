import asyncio
import json

import httpx
import pytest
from test_native_members import add, poll
from test_native_members import members as members
from youtube_backend.database import Database
from youtube_backend.integrations import ExecutionContext
from youtube_backend.local_inference import LocalInference
from youtube_backend.repository import Repository
from youtube_backend.worker import Worker

from youtube_ingestion.integration import create_adapters


async def test_new_worker_and_local_index_reuse_committed_captions(members, monkeypatch):
    env = members
    settings = env.settings
    settings.embedding_provider = "ollama"
    settings.embedding_model = settings.local_embedding_model = "fixture:embed"
    settings.local_embedding_digest = "a" * 64
    settings.embedding_dimensions = 64
    settings.chroma_persist_dir = str(env.rag_config.chroma_persist_dir)
    settings.chunk_target_tokens = 96
    settings.chunk_overlap_tokens = 16
    outgoing = []

    def handler(request):
        outgoing.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "fixture:embed", "digest": "a" * 64}]}
            )
        assert request.url.path == "/api/embed"
        body = json.loads(request.content)
        assert body["truncate"] is False
        return httpx.Response(
            200,
            json={
                "model": "fixture:embed",
                "embeddings": [[1.0] + [0.0] * 63 for _ in body["input"]],
            },
        )

    async def local(context, **kwargs):
        return await LocalInference(context, transport=httpx.MockTransport(handler)).call(**kwargs)

    monkeypatch.setattr(ExecutionContext, "local_inference", local)
    first = await create_adapters(settings=settings, repository=env.repo)
    await first.ingestion.close()
    first.ingestion = env.adapters.ingestion
    entered = asyncio.Event()

    async def interrupted(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(first, "index", interrupted)
    worker = Worker(env.repo, first, settings, report_liveness=False)
    job = await add(env.a)
    assert await add(env.a) == job
    running = asyncio.create_task(worker.run_once(job))
    await asyncio.wait_for(entered.wait(), 10)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert (await poll(env.a, job))["state"] == "queued"
    await first.close()
    # Discard worker/adapter and open a new connection to the same trial database.
    database = Database(settings.database_url)
    repo = Repository(database, settings)
    resumed = await create_adapters(settings=settings, repository=repo)

    async def forbidden(*args):
        pytest.fail("A restarted worker must reuse metadata and captions already committed")

    monkeypatch.setattr(resumed.ingestion.captions, "fetch", forbidden)
    monkeypatch.setattr(resumed.ingestion.metadata, "fetch", forbidden)
    try:
        assert await Worker(repo, resumed, settings, report_liveness=False).run_once(job)
        final = await poll(env.a, job)
        assert final["state"] == "completed" and final["stage"] == "ready", final
        assert final["result"]["chunk_count"] > 0
        assert env.captions.calls == ["dQw4w9WgXcQ"]
        assert "/api/embed" in outgoing and "/api/chat" not in outgoing
        assert (await env.b.get(f"/api/jobs/{job}")).status_code == 404
    finally:
        await resumed.close()
        database.close()
