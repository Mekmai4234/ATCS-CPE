"""Actual v2 HTTP/storage and migration with local PNG/OCR test inputs only."""

import asyncio
import base64
import hashlib
import shutil
import sqlite3
import time

import pytest
import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient
from test_free_tier import context_for
from test_identity import VIDEO, login, ready
from test_identity import identity as identity

from youtube_backend import database as db
from youtube_backend.auth_cli import paired_backup
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.evidence_v2 import MediaEnrichment, SourceSnapshotV2
from youtube_backend.main import create_app
from youtube_backend.media import MediaStore, asset_root
from youtube_backend.migration import alembic_config, upgrade_database
from youtube_backend.provider_errors import provider_error
from youtube_backend.repository import Repository, digest

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
)


def bundle():
    return MediaEnrichment(
        sampling_version="03-uniform-v1",
        ocr_version="tesseract-test-v1",
        prompt_version="no-vision-called-v1",
        source_sha256=hashlib.sha256(b"fixture-media").hexdigest(),
        duration_seconds=10,
        frames=[
            dict(
                timestamp_seconds=2,
                content=PNG,
                mime="image/png",
                ocr_text="[LOCAL OCR FIXTURE] RAG",
            )
        ],
    )


def install_local_adapter(env, monkeypatch, callback=None):
    async def local(video_id, context):
        context.check()
        if callback:
            return await callback(video_id, context)
        return bundle()

    monkeypatch.setattr(env.app.state.adapters.adapter, "enrich", local, raising=False)


def test_visual_only_uses_own_version_and_never_fabricates_transcript(
    identity, monkeypatch, tmp_path
):
    env = identity
    env.settings.media_asset_dir = str(tmp_path / "assets")
    client, _ = login(env, "a")
    install_local_adapter(env, monkeypatch)
    video_id = "NoCaption01"
    imported = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{video_id}"]})
    queued = client.post(
        f"/api/v2/videos/{video_id}/enrichment", headers={"Idempotency-Key": "ocr-once"}
    )
    assert queued.status_code == 202, queued.text
    assert (
        client.post(
            f"/api/v2/videos/{video_id}/enrichment", headers={"Idempotency-Key": "ocr-once"}
        ).json()
        == queued.json()
    )
    asyncio.run(env.worker.run_once(imported.json()["jobs"][0]["job_id"]))
    assert (
        client.get(f"/api/jobs/{imported.json()['jobs'][0]['job_id']}").json()["stage"]
        == "visual_pending"
    )
    asyncio.run(env.worker.run_once(queued.json()["job_id"]))
    result = client.get(f"/api/v2/videos/{video_id}/evidence")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["state"] == "ready" and data["snapshots"][0]["kind"] == "ocr"
    source = SourceSnapshotV2.model_validate(data["snapshots"][0])
    assert "transcript_version" not in source.model_dump()
    assert not data["coverage"]["whole_video_reviewed"]
    assert data["coverage"]["sampled_timestamps"] == [2]
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.transcripts)) == 0
        video = c.execute(sa.select(db.videos)).mappings().one()
        assert video["transcript_version"] is None and video["status"] == "visual_ready"
    assert client.get(data["evidence"][0]["asset_url"]).content == PNG
    # The old transcript-only answer path stays honest until 04/05 implement v2 retrieval.
    denied = client.post("/api/chat", json={"question": "RAG", "scope": {"video_ids": [video_id]}})
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "video_not_ready"


def test_assets_shared_detach_gc_and_orphan_temporary_cleanup(identity, monkeypatch, tmp_path):
    env = identity
    env.settings.media_asset_dir = str(tmp_path / "assets")
    a, _ = login(env, "a")
    ready(env, a)
    install_local_adapter(env, monkeypatch)
    queued = a.post(f"/api/v2/videos/{VIDEO}/enrichment")
    asyncio.run(env.worker.run_once(queued.json()["job_id"]))
    asset = a.get(f"/api/v2/videos/{VIDEO}/evidence").json()["evidence"][0]
    b, other = login(env, "b")
    with env.db.write() as c:
        c.execute(
            db.users.update().where(db.users.c.user_id == other["user_id"]).values(role="admin")
        )
    # Compare public classification rather than random request IDs.
    assert b.get(asset["asset_url"]).status_code == 404
    assert b.get(asset["asset_url"]).json()["error"]["code"] == "asset_not_found"
    assert b.get("/api/media/assets/unknown").json()["error"]["code"] == "asset_not_found"
    ready(env, b)
    assert b.get(asset["asset_url"]).content == PNG
    detached = a.delete(f"/api/videos/{VIDEO}")
    assert detached.status_code == 202
    assert a.get(asset["asset_url"]).status_code == 404
    assert b.get(asset["asset_url"]).content == PNG
    store = MediaStore(env.repo)
    generation_dir = store.root / digest(VIDEO)[:24] / "1"
    orphan = generation_dir / ("0" * 64 + ".tmp")
    orphan.write_bytes(b"interrupted-local-extraction")
    deletion = b.delete(f"/api/videos/{VIDEO}")
    asyncio.run(env.worker.run_once(deletion.json()["job_id"]))
    assert b.get(asset["asset_url"]).status_code == 404
    assert not orphan.exists()
    with env.db.read() as c:
        for key in ("assets", "frames", "revisions", "cache"):
            assert c.scalar(sa.select(sa.func.count()).select_from(db.v2[key])) == 0


def test_generation_fences_integrity_and_private_cache(identity, tmp_path):
    env = identity
    env.settings.media_asset_dir = str(tmp_path / "assets")
    a, owner = login(env, "a")
    ready(env, a)
    context = context_for(env, owner)
    store = MediaStore(env.repo)
    summary = store.publish(context, bundle())
    snapshot = summary["snapshots"][0]
    request_hash = hashlib.sha256(b"fixture-analysis-input").hexdigest()
    store.cache(context, snapshot, "prompt1", "model1", request_hash, {"result": "private"})
    assert store.cache(context, snapshot, "prompt1", "model1", request_hash) == {
        "result": "private"
    }
    assert store.cache(context, snapshot, "prompt1", "model1", "0" * 64) is None
    b, other = login(env, "b")
    ready(env, b)
    env.repo.finish(context.job_id, context.lease_token, {})
    second = context_for(env, other)
    assert store.cache(second, snapshot, "prompt1", "model1", request_hash) is None
    asset_id = a.get(f"/api/v2/videos/{VIDEO}/evidence").json()["evidence"][0]["asset_id"]
    with env.db.read() as c:
        path = c.scalar(sa.select(db.v2["assets"].c.path))
    (store.root / path).write_bytes(b"tampered")
    assert a.get(f"/api/media/assets/{asset_id}").status_code == 409
    with env.db.write() as c:
        c.execute(db.jobs.update().where(db.jobs.c.job_id == second.job_id).values(deadline_at=0))
    with pytest.raises(AppError) as expired:
        store.publish(second, bundle())
    assert expired.value.code == "task_timeout"
    with env.db.write() as c:
        c.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == second.job_id)
            .values(deadline_at=second.deadline_at)
        )
        c.execute(db.videos.update().where(db.videos.c.video_id == VIDEO).values(generation=2))
    assert a.get(f"/api/media/assets/{asset_id}").status_code == 404
    with pytest.raises(AppError):
        store.publish(second, bundle())


@pytest.mark.parametrize("wait_seconds", [10, 3600])
def test_background_429_pauses_without_lease_and_explicit_retry_creates_one_new_job(
    identity, monkeypatch, wait_seconds
):
    env = identity
    a, _ = login(env, "a")
    ready(env, a)

    async def limited(video_id, context):
        raise provider_error(429, retry_after=str(wait_seconds))

    install_local_adapter(env, monkeypatch, limited)
    queued = a.post(f"/api/v2/videos/{VIDEO}/enrichment")
    job_id = queued.json()["job_id"]
    started = time.time()
    asyncio.run(env.worker.run_once(job_id))
    paused = a.get(f"/api/jobs/{job_id}").json()
    assert paused["state"] == "paused"
    assert paused["wait"]["time_source"] == "provider"
    assert "retry_at" in paused["wait"] and "estimated_retry_at" not in paused["wait"]
    from datetime import datetime

    provider_time = datetime.fromisoformat(paused["wait"]["retry_at"]).timestamp()
    assert started + wait_seconds - 1 <= provider_time <= time.time() + wait_seconds + 1
    if wait_seconds < 60:
        assert datetime.fromisoformat(paused["available_at"]).timestamp() >= started + 60
        assert provider_time < datetime.fromisoformat(paused["available_at"]).timestamp()
    with env.db.write() as c:
        row = c.execute(sa.select(db.jobs).where(db.jobs.c.job_id == job_id)).mappings().one()
        assert row["lease_token"] is None and row["lease_until"] is None
        c.execute(
            db.jobs.update().where(db.jobs.c.job_id == job_id).values(deadline_at=time.time() - 1)
        )
    assert env.repo.claim(job_id) is None
    first = a.post(f"/api/jobs/{job_id}/retry")
    assert first.status_code == 202, first.text
    assert first.json()["job_id"] != job_id
    assert a.post(f"/api/jobs/{job_id}/retry").json() == first.json()
    assert env.repo.claim(first.json()["job_id"]) is None  # Keep the known provider wait.
    assert a.get("/api/videos").json()["items"][0]["status"] == "ready"
    assert (
        a.post("/api/chat", json={"question": "RAG", "scope": {"video_ids": [VIDEO]}}).status_code
        == 200
    )


def test_additive_migration_preserves_v1_sessions_history_and_refuses_unbacked_upgrade(
    identity, tmp_path
):
    env = identity
    a, _ = login(env, "a")
    ready(env, a)
    chat = a.post("/api/chat", json={"question": "RAG", "scope": {"video_ids": [VIDEO]}}).json()
    with env.db.engine.begin() as c:
        command.downgrade(alembic_config(c), "0002")
    with pytest.raises(RuntimeError, match="backup"):
        upgrade_database(env.db)
    paired_backup(env.settings, tmp_path / "backup-before-v3")
    upgrade_database(env.db, allow_legacy=True)
    assert a.get("/api/auth/me").status_code == 200
    history = a.get(f"/api/conversations/{chat['conversation_id']}").json()
    assert history["total"] == 2 and history["messages"][1]["content"] == chat["answer"]
    assert a.get(f"/api/jobs/{chat['job_id']}").json()["result"]["answer"] == chat["answer"]
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.v2["assets"])) == 0


def test_stopped_backup_restores_sqlite_and_media_together_on_a_copy(identity, tmp_path):
    env = identity
    env.settings.media_asset_dir = str(tmp_path / "assets")
    a, owner = login(env, "a")
    ready(env, a)
    context = context_for(env, owner)
    MediaStore(env.repo).publish(context, bundle())
    asset_id = a.get(f"/api/v2/videos/{VIDEO}/evidence").json()["evidence"][0]["asset_id"]
    env.repo.finish(context.job_id, context.lease_token, {})
    backup = tmp_path / "complete-backup"
    paired_backup(env.settings, backup)
    restored = tmp_path / "restored.db"
    shutil.copyfile(backup / "app.db", restored)
    settings = Settings(
        **dict(env.settings.model_dump(), database_url=f"sqlite:///{restored.as_posix()}")
    )
    shutil.copytree(backup / "media-assets", asset_root(settings))
    database = Database(settings.database_url)
    restored_repo = Repository(database, settings)
    from youtube_backend.fixture_adapter import FixtureAdapters

    app = create_app(settings, database, FixtureAdapters(restored_repo, settings))
    with TestClient(app) as client:
        client.cookies.update(a.cookies)
        assert client.get(f"/api/media/assets/{asset_id}").content == PNG
    with sqlite3.connect(backup / "app.db") as c:
        assert c.execute("SELECT count(*) FROM media_assets").fetchone()[0] == 1
    with env.db.engine.begin() as c:
        with pytest.raises(RuntimeError, match="backup"):
            command.downgrade(alembic_config(c), "0002")
