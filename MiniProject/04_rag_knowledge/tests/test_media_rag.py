"""Actual 02 media/quota contract + SQLite/Chroma; HTTP and image inputs are fixtures."""

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B
from google import genai
from google.genai import types
from test_authorized_sources import actor
from youtube_backend import database as db
from youtube_backend.errors import AppError
from youtube_backend.evidence_v2 import MediaEnrichment, SourceSnapshotV2
from youtube_backend.media import MediaStore

from youtube_rag.config import RagSettings
from youtube_rag.embedding_cache import EmbeddingCache, embeddings
from youtube_rag.embeddings import GeminiEmbedder
from youtube_rag.manifest import BackendExecution
from youtube_rag.media_manifest import media_runs
from youtube_rag.service import RagService


def bundle(text="ป้ายห้องเรียน RAG", second="Embeddings on a slide"):
    # Labelled minimal signature fixture; no real extraction/OCR quality claim.
    return MediaEnrichment(
        source_sha256=hashlib.sha256(b"fixture-video").hexdigest(),
        sampling_version="fixture-samples-v1",
        ocr_version="fixture-ocr-v1",
        prompt_version="local-only-v1",
        duration_seconds=10,
        frames=[
            dict(
                timestamp_seconds=2,
                content=b"\x89PNG\r\n\x1a\nfixture1",
                mime="image/png",
                ocr_text=text,
            ),
            dict(
                timestamp_seconds=7,
                content=b"\x89PNG\r\n\x1a\nfixture2",
                mime="image/png",
                ocr_text=second,
            ),
        ],
    )


@pytest.fixture
async def media_env(env, tmp_path):
    env.settings.auth_enabled = True
    env.settings.media_asset_dir = str(tmp_path / "assets")
    with env.db.write() as c:
        for user in ("a", "b"):
            c.execute(
                db.users.insert().values(
                    user_id=user,
                    google_sub=f"fixture-{user}",
                    role="user",
                    status="active",
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )
    with actor("a"):
        imported = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
        env.repo.cancel(imported["job_id"])
        queued = MediaStore(env.repo).enqueue(VIDEO_A)
        job = env.repo.claim(queued["job_id"])
    assert job
    ctx = env.context(job)
    data = MediaStore(env.repo).publish(ctx, bundle())
    env.media_ctx = ctx
    env.media_execution = BackendExecution(ctx)
    env.snapshot = SourceSnapshotV2.model_validate(data["snapshots"][0])
    return env


async def test_image_only_literal_thai_search_asset_and_honest_coverage(media_env):
    env = media_env
    receipt = await env.rag.media.index(env.snapshot, env.media_execution, semantic=False)
    assert receipt["prepared_evidence_complete"] and not receipt["semantic_ready"]
    assert not receipt["whole_video_reviewed"] and receipt["sampled_timestamps"] == [2, 7]
    result = await env.rag.media.search("ห้องเรียน", [env.snapshot], env.media_execution)
    assert result["mode"] == "lexical" and not result["semantic_complete"]
    hit = result["hits"][0]
    assert hit["citation"]["start_seconds"] == 2
    assert hit["citation"]["source"]["kind"] == "ocr"
    assert "transcript_version" not in hit["citation"]["source"]
    with actor("a"):
        content, mime = MediaStore(env.repo).asset(hit["citation"]["asset_id"])
    assert content.endswith(b"fixture1") and mime == "image/png"
    assert await env.rag.media.evidence([env.snapshot], [hit["evidence_id"]], env.media_execution)
    miss = await env.rag.media.search("unseen content", [env.snapshot], env.media_execution)
    assert not miss["hits"] and not miss["semantic_complete"] and miss["limitation"]
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.transcripts)) == 0


async def test_media_semantic_and_generation_revision_isolation(media_env):
    env = media_env
    assert (await env.rag.media.index(env.snapshot, env.media_execution))["semantic_ready"]
    hits = await env.rag.media.search("Embeddings", [env.snapshot], env.media_execution)
    assert hits["mode"] == "semantic" and hits["hits"]
    old = env.snapshot
    data = MediaStore(env.repo).publish(env.media_ctx, bundle("ใหม่ OCR", "new revision"))
    current = SourceSnapshotV2.model_validate(data["snapshots"][0])
    for method in (
        lambda: env.rag.media.search("RAG", [old], env.media_execution),
        lambda: env.rag.media.evidence([old], [], env.media_execution),
        lambda: env.rag.media.index(old, env.media_execution),
    ):
        with pytest.raises(AppError, match="revision changed"):
            await method()
    await env.rag.media.index(current, env.media_execution, semantic=False)
    result = await env.rag.media.search("ใหม่", [current], env.media_execution)
    assert result["mode"] == "lexical" and result["hits"]
    wrong = current.model_copy(update={"generation": 2})
    with pytest.raises(AppError):
        await env.rag.media.search("ใหม่", [wrong], env.media_execution)


@pytest.mark.parametrize("operation", ["lexical", "semantic", "evidence", "index"])
async def test_foreign_execution_cannot_read_any_media_path(media_env, operation, monkeypatch):
    env = media_env
    await env.rag.media.index(env.snapshot, env.media_execution)
    with actor("b"):
        imported = env.repo.import_urls([f"https://youtu.be/{VIDEO_B}"])[0]
        env.repo.cancel(imported["job_id"])
        queued = MediaStore(env.repo).enqueue(VIDEO_B)
        job = env.repo.claim(queued["job_id"])
    execution = BackendExecution(env.context(job))

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized request reached embeddings/vectors")

    monkeypatch.setattr(env.rag.media.vectors, "call", forbidden)
    monkeypatch.setattr(env.rag.embedder, "embed", forbidden)
    with pytest.raises(AppError):
        if operation == "evidence":
            await env.rag.media.evidence([env.snapshot], [], execution)
        elif operation == "index":
            await env.rag.media.index(env.snapshot, execution)
        else:
            await env.rag.media.search("RAG", [env.snapshot], execution, mode=operation)


async def test_grant_revoked_during_index_never_publishes(media_env, monkeypatch):
    env = media_env
    original = env.rag.media.vectors.call

    async def revoke(operation, *args, **kwargs):
        result = await original(operation, *args, **kwargs)
        if operation == "upsert":
            with env.db.write() as c:
                c.execute(db.user_videos.delete().where(db.user_videos.c.user_id == "a"))
        return result

    monkeypatch.setattr(env.rag.media.vectors, "call", revoke)
    with pytest.raises(AppError):
        await env.rag.media.index(env.snapshot, env.media_execution)
    with env.db.read() as c:
        assert not c.scalar(sa.select(media_runs.c.run_id).where(media_runs.c.state == "published"))


def policy(env, tmp_path):
    from pydantic import SecretStr

    key = "fixture-key-no-network"
    env.settings.gemini_api_key = SecretStr(key)
    path = tmp_path / "fixture-policy.json"
    env.settings.gemini_free_policy_file = path
    now = datetime.now(UTC)
    path.write_text(
        json.dumps(
            dict(
                tier="free",
                project_ref="fixture-only",
                key_sha256=hashlib.sha256(key.encode()).hexdigest(),
                verified_by="fixture",
                evidence_ref="synthetic-policy-not-account-verification",
                verified_at=(now - timedelta(minutes=1)).isoformat(),
                expires_at=(now + timedelta(hours=1)).isoformat(),
                pools={"fixture": dict(rpm=1000, tpm=1000000, rpd=10000, user_rpm=1000)},
                models=[
                    dict(
                        model="gemini-embedding-2",
                        bucket="fixture",
                        endpoints=["countTokens", "embedContent"],
                        roles=["embedding"],
                        returned_models=["gemini-embedding-2"],
                    )
                ],
            )
        ),
        encoding="utf-8",
    )


def live_rag(env, handler, *, key="fixture-key-no-network"):
    settings = RagSettings(
        _env_file=None,
        gemini_api_key=key,
        embedding_dimensions=128,
        chroma_persist_dir=env.config.chroma_persist_dir,
    )
    client = genai.Client(
        api_key=key,
        vertexai=False,
        http_options=types.HttpOptions(
            httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    return RagService(
        settings,
        env.rag.manifest,
        GeminiEmbedder(settings, client=client, http_client=client._api_client._async_httpx_client),
    )


def reply(request):
    if request.url.path.endswith(":countTokens"):
        return httpx.Response(200, json={"totalTokens": 8})
    assert request.url.path.endswith(":embedContent")  # Never a multi-request SDK batch.
    return httpx.Response(200, json={"embedding": {"values": [1.0] + [0.0] * 127}})


async def test_real_broker_covers_every_http_and_cache_reduces_calls(media_env, tmp_path):
    env, calls = media_env, []
    policy(env, tmp_path)

    def handler(request):
        calls.append(request.url.path)
        return reply(request)

    rag = live_rag(env, handler)
    try:
        await rag.media.index(env.snapshot, env.media_execution)
        assert len(calls) == 4
        await rag.media.index(env.snapshot, env.media_execution)
        assert len(calls) == 4
        await rag.media.search("RAG", [env.snapshot], env.media_execution)
        await rag.media.search("RAG", [env.snapshot], env.media_execution)
        assert len(calls) == 6  # Query checkpoint reused too.
        with env.db.read() as c:
            reservations = list(c.execute(sa.select(db.v2["reservations"])).mappings())
        assert len(reservations) == len(calls)
        assert all(r["state"] == "completed" and r["role"] == "embedding" for r in reservations)
        assert {r["endpoint"] for r in reservations} == {"countTokens", "embedContent"}
        with env.db.write() as c:
            c.execute(db.user_videos.delete().where(db.user_videos.c.user_id == "a"))
        with pytest.raises(AppError):
            await rag.media.search("RAG", [env.snapshot], env.media_execution)
        assert len(calls) == 6
    finally:
        await rag.close()


async def test_429_preserves_checkpoint_lexical_and_atomic_publication(media_env, tmp_path):
    env = media_env
    policy(env, tmp_path)
    calls, fail = [], True

    def handler(request):
        calls.append(request.url.path)
        if fail and len(calls) == 4:
            return httpx.Response(429, json={"error": {"code": 429, "message": "RAW-SECRET"}})
        return reply(request)

    rag = live_rag(env, handler)
    try:
        with pytest.raises(AppError) as caught:
            await rag.media.index(env.snapshot, env.media_execution)
        assert caught.value.code == "provider_rate_limited" and "SECRET" not in str(caught.value)
        with env.db.read() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(embeddings)) == 1
            assert not c.scalar(
                sa.select(media_runs.c.run_id).where(media_runs.c.state == "published")
            )
        result = await rag.media.search("ห้องเรียน", [env.snapshot], env.media_execution)
        assert result["mode"] == "lexical" and result["hits"] and len(calls) == 4
        fail = False
        # Explicitly advance this synthetic provider cooldown; production waits in 02.
        with env.db.write() as c:
            c.execute(db.v2["circuits"].update().values(blocked_until=time.time() - 1))
        receipt = await rag.media.index(env.snapshot, env.media_execution)
        assert receipt["semantic_ready"] and len(calls) == 6  # First frame was not sent again.
    finally:
        await rag.close()


async def test_unverified_project_never_dispatches_and_local_ocr_stays_available(media_env):
    env = media_env

    def forbidden(request):
        raise AssertionError("Unverified project dispatched a provider HTTP request")

    rag = live_rag(env, forbidden)
    try:
        with pytest.raises(AppError) as caught:
            await rag.media.index(env.snapshot, env.media_execution)
        assert caught.value.code == "free_tier_unverified"
        result = await rag.media.search("RAG", [env.snapshot], env.media_execution)
        assert result["mode"] == "lexical" and result["hits"]
    finally:
        await rag.close()


async def test_embedding_key_must_match_the_broker_approved_project(media_env, tmp_path):
    env = media_env
    policy(env, tmp_path)

    def forbidden(request):
        raise AssertionError("A different project's key reached HTTP")

    rag = live_rag(env, forbidden, key="different-project-fixture-key")
    try:
        with pytest.raises(AppError) as caught:
            await rag.media.index(env.snapshot, env.media_execution)
        assert caught.value.code == "free_tier_unverified"
        # Direct embedding calls get the same binding check, before broker dispatch.
        with pytest.raises(AppError) as caught:
            await rag.embedder.embed(["test"], 5, execution=env.media_execution)
        assert caught.value.code == "free_tier_unverified"
    finally:
        await rag.close()


@pytest.mark.parametrize(
    "change", ["owner", "revision", "model", "dimension", "purpose", "title", "policy"]
)
def test_embedding_cache_identity_is_exact(config, env, change):
    scope = {
        "owner": "a",
        "sources": [{"video_id": VIDEO_A, "generation": 1, "evidence_version": "1" * 64}],
    }
    cache = EmbeddingCache(env.db, config)
    prepared, purpose = "title: A | text: RAG", "document"
    vector = [1.0] + [0.0] * 63
    cache.put(scope, prepared, purpose, vector)
    assert cache.get(scope, prepared, purpose) == vector
    if change == "owner":
        scope["owner"] = "b"
    elif change == "revision":
        scope["sources"][0]["evidence_version"] = "2" * 64
    elif change == "model":
        cache.settings = config.model_copy(update={"embedding_model": "different"})
    elif change == "dimension":
        cache.settings = config.model_copy(update={"embedding_dimensions": 128})
    elif change == "purpose":
        purpose = "query"
    elif change == "policy":
        scope["model_policy"] = "reviewed-new-target"
    else:
        prepared = "title: B | text: RAG"
    assert cache.get(scope, prepared, purpose) is None


async def test_no_broker_never_calls_sdk():
    class Forbidden:
        async def count_tokens(self, **kwargs):
            raise AssertionError("Missing broker reached SDK")

    adapter = GeminiEmbedder(
        RagSettings(_env_file=None), client=SimpleNamespace(aio=SimpleNamespace(models=Forbidden()))
    )
    with pytest.raises(AppError) as caught:
        await adapter.embed(["test"], 5)
    assert caught.value.code == "gemini_broker_required"


async def test_visual_observations_use_separate_kind_and_verified_frame_provenance(
    media_env, tmp_path
):
    from youtube_backend.evidence_v2 import VisualCitationV2
    from youtube_backend.quota import ProviderReply

    env = media_env
    policy(env, tmp_path)
    path = env.settings.gemini_free_policy_file
    data = json.loads(path.read_text())
    data["models"].append(
        dict(
            model="fixture-vision",
            bucket="fixture",
            endpoints=["generateContent"],
            returned_models=["fixture-vision"],
            roles=["vision"],
            image_capable=True,
        )
    )
    path.write_text(json.dumps(data))

    async def fixture_vision():
        return ProviderReply("[FIXTURE VISUAL] blue chart", 10, "fixture-vision")

    proof = await env.media_ctx.gemini_call(
        fixture_vision,
        model="fixture-vision",
        endpoint="generateContent",
        input_tokens=10,
        call_key="fixture-vision-1",
        input_hash="1" * 64,
        role="vision",
    )
    value = bundle()
    value.frames[0].visual_text = "[FIXTURE VISUAL] blue chart"
    value.vision_reservation_id, value.requested_model = proof.reservation_id, "fixture-vision"
    value.returned_model, value.vision_input_hash = "fixture-vision", "1" * 64
    published = MediaStore(env.repo).publish(env.media_ctx, value)
    snapshots = [SourceSnapshotV2.model_validate(s) for s in published["snapshots"]]
    assert {s.kind for s in snapshots} == {"ocr", "visual"}
    for snapshot in snapshots:
        await env.rag.media.index(snapshot, env.media_execution)
    result = await env.rag.media.search(
        "blue chart", snapshots, env.media_execution, mode="lexical"
    )
    hit = result["hits"][0]
    assert hit["citation"]["source"]["kind"] == "visual"
    assert MediaStore(env.repo).verify_citation(
        env.media_ctx, VisualCitationV2.model_validate(hit["citation"])
    )
    inventory = await env.rag.media.inventory(snapshots, env.media_execution)
    assert all(r["semantic_ready"] and not r["whole_video_reviewed"] for r in inventory)


async def test_tampered_vector_metadata_is_an_error_not_lexical_fallback(media_env, monkeypatch):
    env = media_env
    await env.rag.media.index(env.snapshot, env.media_execution)
    original = env.rag.media.vectors.call

    async def corrupted(operation, *args, **kwargs):
        if operation == "query":
            return {
                "ids": [["foreign"]],
                "metadatas": [[{"run_id": "foreign", "evidence_id": "foreign"}]],
                "distances": [[0.1]],
            }
        return await original(operation, *args, **kwargs)

    monkeypatch.setattr(env.rag.media.vectors, "call", corrupted)
    with pytest.raises(AppError) as caught:
        await env.rag.media.search("RAG", [env.snapshot], env.media_execution)
    assert caught.value.code == "incomplete_index"


async def test_keyless_adapter_can_index_local_ocr(media_env):
    from youtube_rag.integration import RagAdapters

    env = media_env
    settings = RagSettings(
        _env_file=None, gemini_api_key="", chroma_persist_dir=env.config.chroma_persist_dir
    )
    adapter = RagAdapters(settings=env.settings, repository=env.repo, rag_settings=settings)
    try:
        result = await adapter.index_media(env.snapshot, env.media_ctx, semantic=False)
        assert result["prepared_evidence_complete"] and not result["semantic_ready"]
        result = await adapter.search_media("RAG", [env.snapshot], env.media_ctx)
        assert result["hits"] and result["mode"] == "lexical"
    finally:
        await adapter.close()


async def test_last_member_delete_removes_media_vectors_manifest_and_cache(media_env):
    env = media_env
    await env.rag.media.index(env.snapshot, env.media_execution)
    EmbeddingCache(env.db, env.config).put(
        {"owner": "a", "sources": [env.snapshot.model_dump()]},
        "prepared",
        "document",
        [1.0] + [0.0] * 63,
    )
    with actor("a"):
        env.repo.finish(env.media_ctx.job_id, env.media_ctx.lease_token, {"fixture": "published"})
        queued = env.repo.delete_video(VIDEO_A)
        job = env.repo.claim(queued["job_id"])
    assert job
    await env.adapters.delete(VIDEO_A, 1, env.context(job))
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(media_runs)) == 0
        assert c.scalar(sa.select(sa.func.count()).select_from(embeddings)) == 0
    actual = await env.rag.media.vectors.call("get", 30, include=[])
    assert not actual["ids"]


async def test_long_ocr_splits_vectors_without_losing_original_citation(media_env):
    env = media_env
    text = ("ภาษาไทย " * 2000).strip()
    published = MediaStore(env.repo).publish(env.media_ctx, bundle(text, "second"))
    snapshot = SourceSnapshotV2.model_validate(published["snapshots"][0])
    await env.rag.media.index(snapshot, env.media_execution)
    records, _ = env.rag.media.local(snapshot, env.media_execution)
    parts = env.rag.media.parts(records)
    assert len(parts) > len(records) and all(len(p["text"].encode()) <= 6000 for p in parts)
    first = [p for p in parts if p["evidence_id"] == records[0]["evidence_id"]]
    assert "".join(p["text"] for p in first) == text
    result = await env.rag.media.search("ภาษาไทย", [snapshot], env.media_execution)
    assert result["hits"][0]["citation"]["text"] == text
    assert len({h["evidence_id"] for h in result["hits"]}) == len(result["hits"])


async def test_stopped_gc_removes_retired_media_without_removing_current(media_env):
    from youtube_rag.maintenance import MaintenanceExecution

    env = media_env
    await env.rag.media.index(env.snapshot, env.media_execution)
    await env.rag.media.index(env.snapshot, env.media_execution)
    with pytest.raises(AppError):
        await env.rag.media.cleanup(env.media_execution, include_staging=True)
    env.repo.finish(env.media_ctx.job_id, env.media_ctx.lease_token, {"fixture": "indexed"})
    await env.rag.cleanup(MaintenanceExecution(env.db), include_staging=True)
    with env.db.read() as c:
        states = list(c.execute(sa.select(media_runs.c.state)).scalars())
    assert "published" in states and "retired" not in states and "staging" not in states


async def test_v2_transcript_snapshot_uses_real_v1_transcript_index(env):
    prepared = env.prepare()
    snapshot = SourceSnapshotV2.from_transcript(prepared.source)
    receipt = await env.adapters.index_snapshot(
        snapshot, prepared.ctx, transcript=prepared.transcript
    )
    assert receipt.source == prepared.source and receipt.complete
    env.repo.finish(prepared.ctx.job_id, prepared.ctx.lease_token, receipt.model_dump())
    query = env.query(VIDEO_A)
    result = await env.adapters.search_snapshots("RAG", [snapshot], query.ctx)
    assert result and result[0].chunk.transcript_version == snapshot.evidence_version
    with pytest.raises(AppError):
        await env.adapters.search_snapshots(
            "RAG", [snapshot, snapshot.model_copy(update={"kind": "ocr"})], query.ctx
        )
