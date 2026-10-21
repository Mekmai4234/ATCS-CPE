import json
import shutil
from uuid import uuid4

import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B, transcript
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError

from youtube_rag.binding import MARKER, StoreBinding
from youtube_rag.cli import build_parser, maintenance
from youtube_rag.config import RagSettings
from youtube_rag.configuration import describe_configuration, load_configuration
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.maintenance import MaintenanceExecution
from youtube_rag.manifest import (
    BackendExecution,
    Manifest,
    active,
    chunks,
    initialize,
    runs,
    store_binding,
)
from youtube_rag.service import RagService
from youtube_rag.vectors import ChromaStore


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for field in Settings.model_fields.keys() | RagSettings.model_fields.keys():
        monkeypatch.delenv(field.upper(), raising=False)


def snapshot(env):
    with env.db.read() as connection:
        return [connection.execute(sa.select(table)).all() for table in (active, runs, chunks)]


def config_file(path, env, store):
    values = {
        "APP_ENV": "test",
        "DATABASE_URL": env.settings.database_url,
        "EMBEDDING_PROVIDER": "fixture",
        "EMBEDDING_MODEL": "fixture-hash-v1",
        "EMBEDDING_DIMENSIONS": env.config.embedding_dimensions,
        "CHUNK_TARGET_TOKENS": env.config.chunk_target_tokens,
        "CHUNK_OVERLAP_TOKENS": env.config.chunk_overlap_tokens,
        "CHROMA_PERSIST_DIR": store.as_posix(),
    }
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    return path


@pytest.mark.parametrize("operation", ["reindex", "gc", "delete"])
async def test_wrong_store_rejected_before_any_manifest_mutation(env, tmp_path, operation):
    source = await env.ready()
    before = snapshot(env)
    wrong_path = tmp_path / "wrong-chroma"
    config = env.config.model_copy(update={"chroma_persist_dir": wrong_path})
    service = RagService(config, Manifest(env.db), FixtureEmbedder(config))
    try:
        with pytest.raises(AppError) as caught:
            if operation == "reindex":
                await service.index(
                    source, transcript(), MaintenanceExecution(env.db), allow_reindex=True
                )
            elif operation == "gc":
                await service.cleanup(MaintenanceExecution(env.db), include_staging=True)
            else:
                queued = env.repo.delete_video(VIDEO_A)
                job = env.repo.claim(queued["job_id"])
                await service.delete(VIDEO_A, source.generation, env.context(job))
        assert caught.value.code == "index_store_mismatch"
        assert snapshot(env) == before
        assert not wrong_path.exists()
    finally:
        await service.close()


async def test_cli_runtime_and_maintenance_different_env_files_fail_closed(env, tmp_path):
    source = await env.ready()
    runtime_env = config_file(tmp_path / "runtime.env", env, env.config.chroma_persist_dir)
    wrong_path = tmp_path / "maintenance-chroma"
    wrong_env = config_file(tmp_path / "maintenance.env", env, wrong_path)
    before = snapshot(env)
    for command in ("reindex", "gc"):
        arguments = [command, "--workers-stopped", "--env-file", str(wrong_env)]
        if command == "reindex":
            arguments.extend(["--video-id", VIDEO_A])
        with pytest.raises(AppError) as caught:
            await maintenance(build_parser().parse_args(arguments))
        assert caught.value.code == "index_store_mismatch"
        assert snapshot(env) == before
        assert not wrong_path.exists()
    result = await maintenance(
        build_parser().parse_args(
            [
                "reindex",
                "--workers-stopped",
                "--env-file",
                str(runtime_env),
                "--video-id",
                VIDEO_A,
            ]
        )
    )
    assert result["complete"] and result["source"] == source.model_dump()
    assert await env.rag.inventory([source], MaintenanceExecution(env.db)) == result["chunk_count"]


async def test_maintenance_does_not_create_mistyped_sqlite_path(env, tmp_path):
    wrong_db = tmp_path / "wrong-directory" / "missing.db"
    file = config_file(tmp_path / "wrong-db.env", env, env.config.chroma_persist_dir)
    with file.open("a", encoding="utf-8") as stream:
        stream.write(f"\nDATABASE_URL=sqlite:///{wrong_db.as_posix()}\n")
    with pytest.raises(AppError) as caught:
        await maintenance(
            build_parser().parse_args(
                [
                    "gc",
                    "--workers-stopped",
                    "--env-file",
                    str(file),
                ]
            )
        )
    assert caught.value.code == "index_schema_missing"
    assert not wrong_db.parent.exists()


@pytest.mark.parametrize("marker", [None, "invalid", "other"])
async def test_missing_corrupt_or_other_marker_preserves_index(env, marker):
    source = await env.ready()
    before = snapshot(env)
    path = env.config.chroma_persist_dir / MARKER
    original = path.read_bytes()
    try:
        if marker is None:
            path.unlink()
        else:
            path.write_text(
                "invalid"
                if marker == "invalid"
                else json.dumps(
                    {
                        "version": 1,
                        "store_id": uuid4().hex,
                    }
                ),
                encoding="utf-8",
            )
        with pytest.raises(AppError) as caught:
            await env.rag.index(
                source, transcript(), MaintenanceExecution(env.db), allow_reindex=True
            )
        assert caught.value.code == "index_store_mismatch"
        assert snapshot(env) == before
    finally:
        path.write_bytes(original)


async def test_cleanup_failure_keeps_metadata_for_retry(env, monkeypatch):
    source = await env.ready()

    async def fail(*args, **kwargs):
        raise AppError("embedding_timeout", "injected failure", 503, True)

    original_embed = env.rag.embedder.embed
    monkeypatch.setattr(env.rag.embedder, "embed", fail)
    # A failed replacement leaves a staging row for GC.
    with pytest.raises(AppError):
        await env.rag.index(source, transcript(), MaintenanceExecution(env.db), allow_reindex=True)
    monkeypatch.setattr(env.rag.embedder, "embed", original_embed)
    before = snapshot(env)
    original_call = env.rag.vectors.call

    async def failed_delete(operation, *args, **kwargs):
        if operation == "delete":
            raise AppError("vector_store_error", "injected delete failure", 503, True)
        return await original_call(operation, *args, **kwargs)

    monkeypatch.setattr(env.rag.vectors, "call", failed_delete)
    with pytest.raises(AppError):
        await env.rag.cleanup(MaintenanceExecution(env.db), include_staging=True)
    assert snapshot(env) == before
    monkeypatch.setattr(env.rag.vectors, "call", original_call)
    await env.rag.cleanup(MaintenanceExecution(env.db), include_staging=True)
    assert not env.rag.manifest.garbage(include_staging=True)


async def test_first_embedding_failure_can_retry_without_chroma_database(env, monkeypatch):
    prepared = env.prepare()
    original = env.rag.embedder.embed

    async def fail(*args, **kwargs):
        raise AppError("embedding_timeout", "injected", 503, True)

    monkeypatch.setattr(env.rag.embedder, "embed", fail)
    with pytest.raises(AppError):
        await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    assert not (env.config.chroma_persist_dir / "chroma.sqlite3").exists()
    monkeypatch.setattr(env.rag.embedder, "embed", original)
    receipt = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    assert receipt.complete


async def test_gc_retains_retired_metadata_until_delete_is_verified(env, monkeypatch):
    source = await env.ready()
    original_cleanup = env.rag.cleanup

    async def skip_cleanup(*args, **kwargs):
        pass

    monkeypatch.setattr(env.rag, "cleanup", skip_cleanup)
    await env.rag.index(source, transcript(), MaintenanceExecution(env.db), allow_reindex=True)
    monkeypatch.setattr(env.rag, "cleanup", original_cleanup)
    assert env.rag.manifest.garbage()
    before = snapshot(env)
    original_call = env.rag.vectors.call

    async def ignored_delete(operation, *args, **kwargs):
        if operation == "delete":
            return None
        return await original_call(operation, *args, **kwargs)

    monkeypatch.setattr(env.rag.vectors, "call", ignored_delete)
    with pytest.raises(AppError) as caught:
        await env.rag.cleanup(MaintenanceExecution(env.db), include_staging=True)
    assert caught.value.code == "incomplete_cleanup"
    assert snapshot(env) == before
    monkeypatch.setattr(env.rag.vectors, "call", original_call)
    await env.rag.cleanup(MaintenanceExecution(env.db), include_staging=True)
    assert not env.rag.manifest.garbage()
    assert await env.rag.inventory([source], MaintenanceExecution(env.db)) > 0


async def test_new_database_cannot_adopt_foreign_populated_store(env):
    prepared = env.prepare()
    store = env.rag.vectors
    await store.call(
        "upsert",
        30,
        ids=["foreign"],
        embeddings=[[1.0] * env.config.embedding_dimensions],
        documents=["foreign data"],
        metadatas=[{"run_id": "foreign"}],
    )
    before = snapshot(env)
    with pytest.raises(AppError) as caught:
        await env.rag.index(prepared.source, prepared.transcript, prepared.execution)
    assert caught.value.code == "index_store_mismatch"
    assert snapshot(env) == before
    assert env.rag.manifest.binding() is None
    assert not (env.config.chroma_persist_dir / MARKER).exists()


async def test_gc_does_not_need_provider_credentials(env, tmp_path):
    await env.ready()
    file = config_file(tmp_path / "gc.env", env, env.config.chroma_persist_dir)
    with file.open("a", encoding="utf-8") as stream:
        stream.write(
            "\nEMBEDDING_PROVIDER=gemini\nEMBEDDING_MODEL=gemini-embedding-2\n"
            "EMBEDDING_DIMENSIONS=1536\nGEMINI_API_KEY=\n"
        )
    result = await maintenance(
        build_parser().parse_args(
            [
                "gc",
                "--workers-stopped",
                "--env-file",
                str(file),
            ]
        )
    )
    assert result == {"garbage_collected": True}


async def test_reindex_restart_bilingual_evidence_scope_and_delete(env):
    source = await env.ready()
    other = await env.ready(VIDEO_B)
    execution = MaintenanceExecution(env.db)
    previous = await env.rag.read_video_chunks([source], execution)
    receipt = await env.rag.index(source, transcript(), execution, allow_reindex=True)
    await env.rag.close()
    restarted = RagService(env.config, Manifest(env.db), FixtureEmbedder(env.config))
    env.rag = env.adapters.rag = restarted
    page = await restarted.read_video_chunks([source], execution)
    assert [c.chunk_id for c in page.items] == [c.chunk_id for c in previous.items]
    assert page.inventory.complete and page.total == receipt.chunk_count
    assert await restarted.inventory([source], execution) == page.total
    for question in ("Embeddings vectors", "คำตอบต้องมีหลักฐาน"):
        hits = await restarted.search(question, [source], execution)
        assert hits and all(hit.chunk.video_id == VIDEO_A for hit in hits)
        for hit in hits:
            assert hit.chunk.transcript_version == source.transcript_version
            segment = next(
                s for s in transcript().segments if s.segment_id in hit.chunk.segment_ids
            )
            assert hit.chunk.start_seconds <= segment.start_seconds < hit.chunk.end_seconds
        evidence = await restarted.evidence([source], [hits[0].chunk.chunk_id], execution)
        assert evidence == [hits[0].chunk.evidence()]
    deletion = env.repo.delete_video(VIDEO_A)
    job = env.repo.claim(deletion["job_id"])
    await restarted.delete(VIDEO_A, source.generation, BackendExecution(env.context(job)))
    env.repo.finish(job["job_id"], job["lease_token"], {"deleted": True})
    with pytest.raises(AppError):
        await restarted.search("Embeddings", [source], execution)
    assert await restarted.search("Embeddings", [other], execution)
    assert not any(row["video_id"] == VIDEO_A for row in restarted.manifest.all_runs())


async def test_legacy_index_requires_explicit_verified_binding(env, tmp_path):
    source = await env.ready()
    await env.rag.close()
    with env.db.write() as connection:
        store_binding.drop(connection)
    initialize(env.db)  # Additive upgrade leaves all existing runs/chunks intact.
    (env.config.chroma_persist_dir / MARKER).unlink()
    service = RagService(env.config, Manifest(env.db), FixtureEmbedder(env.config))
    execution = MaintenanceExecution(env.db)
    before = snapshot(env)
    try:
        with pytest.raises(AppError) as caught:
            await service.index(source, transcript(), execution, allow_reindex=True)
        assert caught.value.code == "index_store_unbound"
        wrong_path = tmp_path / "wrong-legacy"
        with pytest.raises(AppError):
            await StoreBinding(service.manifest, wrong_path).adopt(execution)
        assert not wrong_path.exists() and snapshot(env) == before
        # An existing but empty store must also be rejected without creating a collection.
        empty = ChromaStore(wrong_path, env.config.collection_name)
        try:
            assert await empty.call("count", 30) == 0
            with pytest.raises(AppError):
                await StoreBinding(service.manifest, wrong_path).adopt(execution)
        finally:
            await empty.close()
        assert service.manifest.binding() is None and snapshot(env) == before
        await service.binding.adopt(execution)
        assert await service.inventory([source], execution) > 0
    finally:
        await service.close()


async def test_paired_backup_can_move_and_mismatched_restore_is_rejected(env, tmp_path):
    source = await env.ready()
    await env.rag.close()
    db_copy = tmp_path / "restore" / "app.db"
    db_copy.parent.mkdir()
    # SQLAlchemy connections are closed before copying the stopped SQLite pair.
    env.db.close()
    shutil.copy2(tmp_path / "app.db", db_copy)
    restored_store = tmp_path / "restore" / "chroma"
    shutil.copytree(env.config.chroma_persist_dir, restored_store)
    database = Database(f"sqlite:///{db_copy.as_posix()}")
    config = env.config.model_copy(update={"chroma_persist_dir": restored_store})
    service = RagService(config, Manifest(database), FixtureEmbedder(config))
    try:
        execution = MaintenanceExecution(database)
        assert await service.inventory([source], execution) > 0
        assert await service.search("Embeddings vectors", [source], execution)
        marker = restored_store / MARKER
        marker.write_text(json.dumps({"version": 1, "store_id": uuid4().hex}), encoding="utf-8")
        with pytest.raises(AppError, match="do not match"):
            await service.cleanup(execution, include_staging=True)
    finally:
        await service.close()
        database.close()


def test_explicit_env_precedence_and_secret_free_diagnostics(tmp_path, monkeypatch):
    first, second = tmp_path / "first.env", tmp_path / "second.env"
    first.write_text(
        "EMBEDDING_DIMENSIONS=256\nCHROMA_PERSIST_DIR=runtime/first\n", encoding="utf-8"
    )
    second.write_text(
        "EMBEDDING_DIMENSIONS=512\nCHROMA_PERSIST_DIR=runtime/second\nGEMINI_API_KEY=test-secret\n",
        encoding="utf-8",
    )
    backend, config, profile = load_configuration(env_files=[first, second])
    assert config.embedding_dimensions == 512
    assert config.chroma_persist_dir.name == "second"
    assert backend.chroma_persist_dir == "runtime/second"
    assert "test-secret" not in json.dumps(describe_configuration(backend, config, profile))
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    assert load_configuration(env_files=[first, second])[1].embedding_dimensions == 768
    with pytest.raises(ValueError, match="must exist"):
        load_configuration(env_files=[tmp_path / "missing.env"])


@pytest.mark.parametrize(
    "profile,factory,constant",
    [
        ("team05", "youtube_answers.team:create_adapters", "TEAM05_ENV_FILES"),
        ("ingestion03", "youtube_ingestion.integration:create_adapters", "INGESTION03_ENV_FILES"),
    ],
)
def test_auto_profile_matches_runtime_env_order(tmp_path, monkeypatch, profile, factory, constant):
    import youtube_rag.configuration as configuration

    root, local04, local05 = [tmp_path / name for name in ("root.env", "04.env", "05.env")]
    root.write_text("EMBEDDING_DIMENSIONS=256\n", encoding="utf-8")
    local04.write_text("CHROMA_PERSIST_DIR=runtime/chroma04\n", encoding="utf-8")
    local05.write_text("CHROMA_PERSIST_DIR=runtime/answers05/chroma\n", encoding="utf-8")
    monkeypatch.setattr(configuration, constant, (root, local04, local05))
    monkeypatch.setenv("ADAPTER_FACTORY", factory)
    backend, actual, selected = load_configuration()
    runtime = RagSettings(_env_file=(root, local04, local05))
    assert selected == profile
    assert actual.model_dump() == runtime.model_dump()
    assert backend.database_url


def test_auto_backend_profile_uses_runtime_offline_overrides(tmp_path):
    path = tmp_path / "backend.env"
    path.write_text(
        "APP_ENV=test\nADAPTER_FACTORY=youtube_backend.team:create_adapters\nBACKEND_INTEGRATION_PROFILE=offline\nCHROMA_PERSIST_DIR=runtime/backend\n",
        encoding="utf-8",
    )
    _, config, profile = load_configuration(env_files=[path])
    assert profile == "backend"
    assert (config.embedding_provider, config.embedding_model, config.embedding_dimensions) == (
        "fixture",
        "fixture-hash-v1",
        64,
    )
