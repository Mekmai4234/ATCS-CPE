import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from youtube_rag.evaluation import evaluate

MODULE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recovery07", MODULE / "scripts" / "recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


async def test_cold_restore_reopens_actual_sqlite_chroma_and_identical_evidence(tmp_path):
    state, bundle, restored = (tmp_path / name for name in ("state", "backup", "restored"))
    seed = await evaluate(state)
    image = state / "media" / "generation-1" / "frame.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fixture-private-image-not-real-ocr")
    canonical = state / "media-assets" / "original-db-namespace" / "frame.png"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"fixture-current-module02-asset")
    (state / ".env").write_text("GEMINI_API_KEY=DO-NOT-COPY", encoding="utf-8")
    manifest = recovery.backup(state, bundle, stopped=True)
    assert "app.db" in manifest["files"] and any(k.startswith("chroma/") for k in manifest["files"])
    assert not (bundle / ".env").exists()
    assert manifest["version"] == 2
    assert "media/generation-1/frame.png" in manifest["files"]
    assert "media-assets/original-db-namespace/frame.png" in manifest["files"]
    recovery.restore(bundle, restored)
    # Prove restored reads are independent of the source, after all clients were closed.
    shutil.rmtree(state)
    assert (
        restored / "media/generation-1/frame.png"
    ).read_bytes() == b"fixture-private-image-not-real-ocr"
    assert (
        restored / "media-assets/original-db-namespace/frame.png"
    ).read_bytes() == b"fixture-current-module02-asset"
    verified = await evaluate(restored, phase="verify")
    assert verified["restart_verified"]
    assert verified["checks"] == seed["checks"]
    assert verified["chunks"] == seed["chunks"] and verified["scope_checks_passed"]


def test_backup_requires_stopped_acknowledgement(tmp_path):
    with pytest.raises(ValueError, match="Stop ALL"):
        recovery.backup(tmp_path / "state", tmp_path / "bundle")


def test_restore_rejects_checksum_mismatch_before_creating_destination(tmp_path):
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "app.db").write_bytes(b"corrupt")
    (source / "backup.json").write_text(
        json.dumps(
            {
                "version": 1,
                "files": {"app.db": "0" * 64},
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "restore"
    with pytest.raises(ValueError, match="checksum"):
        recovery.restore(source, target)
    assert not target.exists()


def test_restore_rejects_traversal_and_overwrite(tmp_path):
    source = tmp_path / "bundle"
    source.mkdir()
    (source / "backup.json").write_text(
        json.dumps(
            {
                "version": 1,
                "files": {"../outside": "bad", "app.db": "bad"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outside"):
        recovery.restore(source, tmp_path / "restore")
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        recovery.restore(source, target)


def test_restore_still_accepts_a_v1_manifest_and_checks_v2_media_bytes(tmp_path):
    state, bundle = tmp_path / "state", tmp_path / "backup"
    (state / "chroma").mkdir(parents=True)
    with sqlite3.connect(state / "app.db") as connection:
        connection.execute("CREATE TABLE jobs(state TEXT)")
    manifest = recovery.backup(state, bundle, stopped=True)
    manifest["version"] = 1
    (bundle / "backup.json").write_text(json.dumps(manifest), encoding="utf-8")
    recovery.restore(bundle, tmp_path / "v1-restored")
    (state / "media").mkdir()
    (state / "media/frame.png").write_bytes(b"private-image")
    recovery.backup(state, tmp_path / "v2-backup", stopped=True)
    (tmp_path / "v2-backup/media/frame.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        recovery.restore(tmp_path / "v2-backup", tmp_path / "v2-restored")
    assert not (tmp_path / "v2-restored").exists()
