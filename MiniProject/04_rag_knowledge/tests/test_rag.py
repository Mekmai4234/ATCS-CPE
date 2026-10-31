import asyncio
import time

import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B, expire, transcript
from youtube_backend.errors import AppError, LeaseLost

from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.manifest import Manifest, active
from youtube_rag.service import RagService


async def test_real_chroma_index_query_evidence_inventory_and_pagination(env):
    source = await env.ready()
    query = env.query(VIDEO_A)
    hits = await env.rag.search("Embeddings vectors", query.sources, query.execution, top_k=2)
    assert "s2" in hits[0].chunk.segment_ids
    assert hits[0].chunk.video_id == VIDEO_A
    assert hits[0].chunk.start_seconds <= 12 < hits[0].chunk.end_seconds
    assert -1 <= hits[0].ranking_score <= 1
    records, cursor = [], None
    while True:
        page = await env.rag.read_video_chunks(
            query.sources, query.execution, limit=1, cursor=cursor
        )
        records += page.items
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    count = await env.adapters.inventory([source], query.ctx)
    assert len(records) == len({c.chunk_id for c in records}) == count == page.total
    assert page.inventory.complete
    evidence = await env.adapters.evidence([source], [hits[0].chunk.chunk_id, "unknown"], query.ctx)
    assert evidence == [hits[0].chunk.evidence()]


async def test_retry_reuses_published_vectors_without_embedding_again(env, monkeypatch):
    prepared = env.prepare()
    first = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Existing valid index should not be embedded again")

    monkeypatch.setattr(env.rag.embedder, "embed", forbidden)
    second = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    assert first == second
    assert await env.rag.vectors.call("count", 30) == first.chunk_count


async def test_partial_embedding_failure_is_invisible_then_retry_succeeds(env, monkeypatch):
    prepared = env.prepare()
    env.rag.settings.embedding_batch_size = 1
    original = env.rag.embedder.embed
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AppError("embedding_timeout", "temporary", 503, True)
        return await original(*args, **kwargs)

    monkeypatch.setattr(env.rag.embedder, "embed", fail_second)
    with pytest.raises(AppError, match="temporary"):
        await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    with env.db.read() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(active)) == 0
    assert env.repo.get_job(prepared.job["job_id"])["stage"] == "indexing"
    monkeypatch.setattr(env.rag.embedder, "embed", original)
    receipt = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    assert await env.adapters.inventory([prepared.source], prepared.ctx) == receipt.chunk_count


@pytest.mark.parametrize("mutation", ["expire", "cancel", "delete", "deadline"])
async def test_stale_execution_cannot_publish_after_vector_write(env, monkeypatch, mutation):
    prepared = env.prepare()
    original = env.rag.manifest.publish

    def intercepted(*args):
        if mutation == "expire":
            expire(env, prepared.job)
        elif mutation == "cancel":
            env.repo.cancel(prepared.job["job_id"])
        elif mutation == "delete":
            env.repo.delete_video(VIDEO_A)
        else:
            prepared.ctx.deadline_at = time.time() - 1
        return original(*args)

    monkeypatch.setattr(env.rag.manifest, "publish", intercepted)
    with pytest.raises((AppError, LeaseLost)):
        await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    with env.db.read() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(active)) == 0


async def test_scope_is_enforced_before_search_and_exact_id_lookup(env):
    source_a = await env.ready(VIDEO_A)
    source_b = await env.ready(VIDEO_B)
    query = env.query(VIDEO_A)
    hits = await env.rag.search("Embeddings", [source_a], query.execution)
    assert {h.chunk.video_id for h in hits} == {VIDEO_A}
    with pytest.raises(AppError, match="authorized scope"):
        await env.rag.search("Embeddings", [source_b], query.execution)
    with pytest.raises(AppError, match="nonempty"):
        await env.rag.search("Embeddings", [], query.execution)
    wrong = source_a.model_copy(update={"transcript_version": "old"})
    with pytest.raises(AppError, match="authorized scope"):
        await env.rag.evidence([wrong], [], query.execution)


async def test_channel_and_date_scope_resolved_by_backend(env):
    await env.ready(VIDEO_A)
    other = transcript(VIDEO_B)
    other.channel_id = "channel-b"
    from datetime import date

    other.published_at = date(2020, 1, 1)
    await env.ready(VIDEO_B, value=other)
    query = env.query(VIDEO_A, VIDEO_B, channel_ids=["channel-a"], date_from="2025-01-01")
    hits = await env.rag.search("evidence", query.sources, query.execution)
    assert {s.video_id for s in query.sources} == {VIDEO_A}
    assert all(hit.chunk.video_id == VIDEO_A for hit in hits)
    with pytest.raises(AppError, match="Playlist"):
        env.query(VIDEO_A, playlist_ids=["unsupported"])


async def test_embedding_change_requires_explicit_migration(env):
    await env.ready()
    query = env.query(VIDEO_A)
    changed = env.config.model_copy(update={"embedding_dimensions": 32})
    other = RagService(changed, Manifest(env.db), FixtureEmbedder(changed))
    try:
        with pytest.raises(AppError, match="explicitly reindex"):
            await other.search("RAG", query.sources, query.execution)
    finally:
        await other.close()


async def test_restart_reopens_chroma_and_manifest(env):
    await env.ready()
    query = env.query(VIDEO_A)
    first = await env.rag.search("Embeddings vectors", query.sources, query.execution)
    await env.rag.close()
    restarted = RagService(env.config, Manifest(env.db), FixtureEmbedder(env.config))
    try:
        second = await restarted.search("Embeddings vectors", query.sources, query.execution)
        assert [h.chunk.chunk_id for h in first] == [h.chunk.chunk_id for h in second]
    finally:
        await restarted.close()


async def test_deletion_removes_vectors_and_reimport_uses_new_generation(env):
    old = await env.ready()
    deletion = env.repo.delete_video(VIDEO_A)
    job = env.repo.claim(deletion["job_id"])
    ctx = env.context(job)
    await env.adapters.delete(VIDEO_A, old.generation, ctx)
    await env.adapters.delete(VIDEO_A, old.generation, ctx)
    env.repo.finish(job["job_id"], job["lease_token"], {"deleted": True})
    assert await env.rag.vectors.call("count", 30) == 0
    new = await env.ready()
    assert new.generation > old.generation
    query = env.query(VIDEO_A)
    hits = await env.rag.search("RAG", [new], query.execution)
    assert all(h.chunk.generation == new.generation for h in hits)
    with pytest.raises((AppError, LeaseLost)):
        await env.adapters.delete(VIDEO_A, old.generation, ctx)
    assert await env.adapters.inventory([new], query.ctx) > 0


async def test_missing_index_coverage_is_explicit(env):
    await env.ready()
    query = env.query(VIDEO_A)
    with env.db.write() as connection:
        connection.execute(active.delete())
    page = await env.rag.read_video_chunks(query.sources, query.execution)
    assert not page.inventory.complete
    assert page.inventory.expected_chunks is None
    assert page.inventory.available_chunks == 0
    assert page.inventory.missing_sources == query.sources
    assert page.items == []
    with pytest.raises(AppError, match="missing"):
        await env.rag.search("RAG", query.sources, query.execution)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_k": 0},
        {"top_k": True},
        {"top_k": 101},
        {"min_score": float("nan")},
        {"min_score": "invalid"},
    ],
)
async def test_search_rejects_invalid_limits_without_any_provider_call(env, kwargs):
    with pytest.raises(AppError):
        await env.rag.search("RAG", [], None, **kwargs)


async def test_cursor_and_no_match_threshold(env):
    await env.ready()
    query = env.query(VIDEO_A)
    with pytest.raises(AppError, match="Cursor"):
        await env.rag.read_video_chunks(query.sources, query.execution, cursor="invalid!")
    hits = await env.rag.search(
        "completelyunrelatedxyz", query.sources, query.execution, min_score=0.9999
    )
    assert hits == []


async def test_invalid_embedding_and_transcript_never_publish(env, monkeypatch):
    prepared = env.prepare()

    async def invalid(texts, timeout, **kwargs):
        return [[float("nan")]] * len(texts)

    monkeypatch.setattr(env.rag.embedder, "embed", invalid)
    with pytest.raises(AppError, match="invalid shape"):
        await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    prepared.transcript.segments[0].text = "tampered"
    with pytest.raises(AppError, match="does not match its version"):
        await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)


async def test_cancellation_kills_chroma_process_and_restart_is_safe(env):
    await env.rag.vectors.call("count", 60)
    old = env.rag.vectors.process
    task = asyncio.create_task(env.rag.vectors.call("count", 0.000001))
    with pytest.raises(AppError):
        await task
    assert old.returncode is not None
    assert await env.rag.vectors.call("count", 60) == 0


async def test_inventory_detects_missing_vectors(env):
    await env.ready()
    query = env.query(VIDEO_A)
    rows, _ = env.rag.manifest.current(query.sources, env.config.fingerprint)
    await env.rag.vectors.call("delete", 30, where={"run_id": rows[0]["run_id"]})
    with pytest.raises(AppError, match="inventory is incomplete"):
        await env.adapters.inventory(query.sources, query.ctx)


async def test_short_context_is_complete_scoped_and_never_embeds_query(env, monkeypatch):
    await env.ready()
    query = env.query(VIDEO_A)

    async def forbidden(*args, **kwargs):
        raise AssertionError("short context must not call the embedding provider")

    monkeypatch.setattr(env.rag.embedder, "embed", forbidden)
    chunks = await env.rag.short_context(query.sources, query.execution)
    assert chunks and all(c.video_id == VIDEO_A for c in chunks)
    assert await env.rag.short_context(query.sources, query.execution, max_bytes=1) is None
