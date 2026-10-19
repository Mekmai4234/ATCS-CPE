"""Cold backup/restore of an explicitly stopped SQLite + Chroma state directory."""

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path, PurePosixPath


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def validate_state(source):
    if not (source / "app.db").is_file() or not (source / "chroma").is_dir():
        raise ValueError("State must contain app.db and chroma/")
    if any(p.is_symlink() for p in [source, *source.rglob("*")]):
        raise ValueError("Symlinks are not allowed in a state bundle")
    connection = sqlite3.connect((source / "app.db").as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        busy = connection.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('queued', 'running')"
        ).fetchone()[0]
        if busy:
            raise ValueError("Finish/cancel pending jobs before making a cold backup")
    finally:
        connection.close()


def separate(source, target):
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Source and destination must be separate directory trees")
    if target.exists():
        raise ValueError("Destination must not exist; restore never overwrites data")


def backup(source, target, *, stopped=False):
    if not stopped:
        raise ValueError("Stop ALL API/workers/Chroma clients and acknowledge --services-stopped")
    source, target = Path(source).resolve(), Path(target).resolve()
    separate(source, target)
    validate_state(source)
    files = [
        p
        for p in source.rglob("*")
        if p.is_file()
        and (
            p.relative_to(source).parts[0] == "chroma"
            or p.name in {"app.db", "app.db-wal", "app.db-shm", "seed-result.json"}
            and p.parent == source
        )
    ]
    target.mkdir(parents=True)
    for path in files:
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    validate_state(target)
    manifest = dict(
        version=1,
        method="cold-copy",
        files={
            p.relative_to(target).as_posix(): digest(p) for p in target.rglob("*") if p.is_file()
        },
    )
    (target / "backup.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def restore(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    separate(source, target)
    if source.is_symlink() or any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("Symlinks are not allowed in a backup")
    manifest = json.loads((source / "backup.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("Unsupported backup version")
    if not isinstance(manifest.get("files"), dict) or "app.db" not in manifest["files"]:
        raise ValueError("Backup must list its SQLite database")
    for name, expected in manifest["files"].items():
        if (
            not isinstance(name, str)
            or PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or "\\" in name
            or ":" in name
        ):
            raise ValueError("Backup path outside bundle")
        path = (source / name).resolve()
        if source not in path.parents or not path.is_file() or digest(path) != expected:
            raise ValueError("Backup file missing, outside bundle, or checksum mismatch")
    actual = {
        p.relative_to(source).as_posix()
        for p in source.rglob("*")
        if p.is_file() and p.name != "backup.json"
    }
    if actual != set(manifest["files"]):
        raise ValueError("Backup manifest does not cover all files")
    validate_state(source)
    target.mkdir(parents=True)
    for name in manifest["files"]:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, dest)
    validate_state(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--services-stopped", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "backup":
            backup(args.source, args.destination, stopped=args.services_stopped)
        else:
            restore(args.source, args.destination)
    except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
        parser.exit(1, f"Recovery refused: {exc}\n")
    print(
        "Cold recovery operation completed; verify inventory/citations before switching services."
    )


if __name__ == "__main__":
    main()
