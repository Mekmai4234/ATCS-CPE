import asyncio

import pytest
from conftest import VIDEO_A, expire, transcript
from youtube_backend.errors import AppError, LeaseLost
from youtube_backend.schemas import Citation
from youtube_backend.worker import Worker

from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.evaluation import ReferencePipeline
from youtube_rag.maintenance import MaintenanceExecution
from youtube_rag.manifest import Manifest, initialize, schema
from youtube_rag.service import RagService


async def test_real_backend_worker_marks_ready_only_after_verified_chroma_inventory(env):
    pipeline = ReferencePipeline(env.repo, env.settings, env.adapters, [transcript()])
    worker = Worker(env.repo, pipeline, env.settings)
    item = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
    assert await worker.run_once(item["job_id"])
    job = env.repo.get_job(item["job_id"])
    assert job["stage"] == "ready" and job["result"]["complete"] is True
    assert job["result"]["chunk_count"] > 0
    query = env.query(VIDEO_A)
    hits = await env.rag.search("Embeddings", query.sources, query.execution, top_k=1)
    evidence = (await env.adapters.evidence(query.sources, [hits[0].chunk.chunk_id], query.ctx))[0]
    env.repo.check_evidence_bounds(evidence)
    citation = Citation(
        citation_id="c1", **evidence.model_dump(exclude={"text", "transcript_version"})
    )
    assert citation.start_seconds == hits[0].chunk.start_seconds


async def test_worker_heartbeat_renews_during_real_chroma_startup(env):
    env.settings.job_lease_seconds = 0.3
    pipeline = ReferencePipeline(env.repo, env.settings, env.adapters, [transcript()])
    worker = Worker(env.repo, pipeline, env.settings)
    item = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
    await worker.run_once(item["job_id"])
    job = env.repo.get_job(item["job_id"])
    assert job["stage"] == "ready"
    assert job["attempt_count"] == 1


async def test_replaced_transcript_retires_and_removes_old_vectors(env):
    prepared = env.prepare()
    old_receipt = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    changed = transcript(text="New transcript version about cooking rice")
    new_source = env.repo.save_transcript(
        prepared.job["job_id"], prepared.job["lease_token"], changed
    )
    receipt = await env.adapters.index(new_source, changed, prepared.ctx)
    assert receipt.source.transcript_version != old_receipt.source.transcript_version
    assert await env.rag.vectors.call("count", 30) == receipt.chunk_count
    with pytest.raises(AppError):
        await env.adapters.inventory([prepared.source], prepared.ctx)


async def test_lease_recovery_cannot_be_overwritten_by_old_worker(env):
    prepared = env.prepare()
    expire(env, prepared.job)
    replacement = env.repo.claim(prepared.job["job_id"])
    new_ctx = env.context(replacement)
    env.repo.stage(replacement["job_id"], replacement["lease_token"], "indexing")
    receipt = await env.adapters.index(prepared.source, prepared.transcript, new_ctx)
    with pytest.raises(LeaseLost):
        await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    assert await env.adapters.inventory([prepared.source], new_ctx) == receipt.chunk_count


async def test_explicit_embedding_migration_preserves_ready_backend_source(env):
    source = await env.ready()
    config = env.config.model_copy(update={"embedding_dimensions": 32})
    service = RagService(config, Manifest(env.db), FixtureEmbedder(config))
    try:
        receipt = await service.index(
            source, transcript(), MaintenanceExecution(env.db), allow_reindex=True
        )
        assert receipt.source == source
        query = env.query(VIDEO_A)
        hits = await service.search("Embeddings vectors", [source], query.execution)
        assert hits
        with pytest.raises(AppError, match="explicitly reindex"):
            await env.rag.search("Embeddings", [source], query.execution)
    finally:
        await service.close()


async def test_maintenance_refuses_active_jobs(env):
    prepared = env.prepare()
    with pytest.raises(AppError, match="stop API/workers"):
        await env.rag.index(
            prepared.source, prepared.transcript, MaintenanceExecution(env.db), allow_reindex=True
        )


async def test_failed_reindex_leaves_previous_complete_index_readable(env, monkeypatch):
    source = await env.ready()
    execution = MaintenanceExecution(env.db)

    async def failure(*args, **kwargs):
        raise AppError("embedding_timeout", "injected failure", 503, True)

    original = env.rag.embedder.embed
    monkeypatch.setattr(env.rag.embedder, "embed", failure)
    with pytest.raises(AppError, match="injected failure"):
        await env.rag.index(source, transcript(), execution, allow_reindex=True)
    monkeypatch.setattr(env.rag.embedder, "embed", original)
    assert await env.rag.inventory([source], execution) > 0
    await env.rag.cleanup(execution, include_staging=True)
    assert await env.rag.vectors.call("count", 30) == await env.rag.inventory([source], execution)


async def test_cancel_during_chroma_operation_reaps_subprocess(env):
    await env.rag.vectors.call("count", 60)
    old = env.rag.vectors.process
    # Hold a request waiting for a reply deterministically, without an unbounded fake thread.
    original = old.stdout.readline
    entered = asyncio.Event()

    async def blocked():
        entered.set()
        await asyncio.Event().wait()

    old.stdout.readline = blocked
    task = asyncio.create_task(env.rag.vectors.call("count", 60))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    old.stdout.readline = original
    assert old.returncode is not None
    assert await env.rag.vectors.call("count", 60) == 0


async def test_schema_setup_is_repeatable_and_rejects_unknown_version(env):
    initialize(env.db)
    with env.db.write() as connection:
        connection.execute(schema.update().values(version=999))
    with pytest.raises(AppError, match="Unsupported"):
        Manifest(env.db)
    with pytest.raises(AppError, match="Unsupported"):
        initialize(env.db)


async def test_additive_setup_restores_embedding_cache_without_replacing_library(env):
    from youtube_rag.embedding_cache import EmbeddingCache, embeddings

    source = await env.ready()
    query = env.query(VIDEO_A)
    before = await env.rag.inventory([source], query.execution)
    cursor_key = env.rag.manifest.cursor_key()
    with env.db.write() as connection:
        embeddings.drop(connection)

    initialize(env.db)
    cache = EmbeddingCache(env.db, env.config)
    scope = {"sources": [source.model_dump()]}
    assert cache.get(scope, "query", "query") is None
    assert env.rag.manifest.cursor_key() == cursor_key
    assert await env.rag.inventory([source], query.execution) == before
    hits = await env.rag.search("Embeddings", [source], query.execution, top_k=1)
    assert hits and hits[0].chunk.video_id == source.video_id


async def test_inventory_receipt_mismatch_prevents_backend_ready(env, monkeypatch):
    pipeline = ReferencePipeline(env.repo, env.settings, env.adapters, [transcript()])
    worker = Worker(env.repo, pipeline, env.settings)

    async def wrong(*args):
        return 9999

    monkeypatch.setattr(pipeline, "inventory", wrong)
    item = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
    await worker.run_once(item["job_id"])
    job = env.repo.get_job(item["job_id"])
    assert job["state"] == "failed" and job["error_code"] == "incomplete_index"


async def test_cursor_cannot_mix_index_snapshots(env):
    source = await env.ready()
    execution = MaintenanceExecution(env.db)
    page = await env.rag.read_video_chunks([source], execution, limit=1)
    assert page.next_cursor
    await env.rag.index(source, transcript(), execution, allow_reindex=True)
    with pytest.raises(AppError, match="index has changed"):
        await env.rag.read_video_chunks([source], execution, cursor=page.next_cursor)


async def test_title_only_change_replaces_embedding_input_without_changing_transcript(env):
    prepared = env.prepare()
    first = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    before, _ = env.rag.manifest.current([prepared.source], env.config.fingerprint)
    prepared.transcript.title = "[FIXTURE] Updated retrieval title"
    second = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    after, _ = env.rag.manifest.current([prepared.source], env.config.fingerprint)
    assert first.source == second.source and first.chunk_count == second.chunk_count
    assert before[0]["run_id"] != after[0]["run_id"]
    records = env.rag.manifest.page([after[0]["run_id"]], 0, 200)
    assert all(c.title == prepared.transcript.title for c in records)
    assert await env.rag.vectors.call("count", 30) == second.chunk_count
