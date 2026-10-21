import importlib.util
import json
import shutil
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
    (state / ".env").write_text("GEMINI_API_KEY=DO-NOT-COPY", encoding="utf-8")
    manifest = recovery.backup(state, bundle, stopped=True)
    assert "app.db" in manifest["files"] and any(k.startswith("chroma/") for k in manifest["files"])
    assert not (bundle / ".env").exists()
    recovery.restore(bundle, restored)
    # Prove restored reads are independent of the source, after all clients were closed.
    shutil.rmtree(state)
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
