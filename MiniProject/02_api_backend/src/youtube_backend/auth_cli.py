"""Explicit operator actions; never bootstrap admin or claim data during login."""

import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from . import database as db
from .config import PROJECT_ROOT, Settings
from .database import Database
from .migration import upgrade_database


def bootstrap(database, sub):
    with database.write() as c:
        if c.scalar(
            sa.select(sa.func.count())
            .select_from(db.users)
            .where(db.users.c.role == "admin", db.users.c.status == "active")
        ):
            raise ValueError("An administrator already exists; use authenticated administration")
        user = (
            c.execute(
                sa.select(db.users).where(
                    db.users.c.google_sub == sub, db.users.c.status == "active"
                )
            )
            .mappings()
            .one()
        )
        c.execute(
            db.users.update().where(db.users.c.user_id == user["user_id"]).values(role="admin")
        )
        c.execute(
            db.sessions.update()
            .where(db.sessions.c.user_id == user["user_id"])
            .values(revoked=True)
        )
        c.execute(
            db.admin_audit.insert().values(
                actor_id=None,
                target_id=user["user_id"],
                action="bootstrap_admin",
                data={"explicit_operator_action": True},
                created_at=time.time(),
            )
        )


def claim_legacy(database, *, admin_sub, owner_sub):
    with database.write() as c:
        admin = (
            c.execute(
                sa.select(db.users).where(
                    db.users.c.google_sub == admin_sub,
                    db.users.c.role == "admin",
                    db.users.c.status == "active",
                )
            )
            .mappings()
            .one()
        )
        owner = (
            c.execute(
                sa.select(db.users).where(
                    db.users.c.google_sub == owner_sub, db.users.c.status == "active"
                )
            )
            .mappings()
            .one()
        )
        for table in (db.jobs, db.conversations, db.artifacts):
            c.execute(
                table.update().where(table.c.owner_id.is_(None)).values(owner_id=owner["user_id"])
            )
        for video_id in c.scalars(
            sa.select(db.videos.c.video_id)
            .join(db.legacy_sources)
            .where(db.videos.c.status.not_in(["deleted", "deleting"]))
        ):
            if not c.scalar(
                sa.select(db.user_videos.c.video_id).where(
                    db.user_videos.c.user_id == owner["user_id"],
                    db.user_videos.c.video_id == video_id,
                )
            ):
                c.execute(
                    db.user_videos.insert().values(
                        user_id=owner["user_id"], video_id=video_id, created_at=time.time()
                    )
                )
        c.execute(db.legacy_sources.delete())
        c.execute(
            db.admin_audit.insert().values(
                actor_id=admin["user_id"],
                target_id=owner["user_id"],
                action="claim_legacy",
                data={"explicit_operator_action": True},
                created_at=time.time(),
            )
        )


def paired_backup(settings, destination):
    source = Path(make_url(settings.database_url).database).resolve()
    chroma = Path(settings.chroma_persist_dir)
    chroma = (chroma if chroma.is_absolute() else PROJECT_ROOT / chroma).resolve()
    destination = destination.resolve()
    if destination == chroma or chroma in destination.parents:
        raise ValueError("Backup must be outside the Chroma directory")
    if not source.is_file():
        raise ValueError("Existing database is required for legacy migration")
    with sqlite3.connect(source) as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            "videos" in names
            and connection.execute(
                "SELECT count(*) FROM videos WHERE status='deleting'"
            ).fetchone()[0]
        ):
            raise ValueError("Finish committed deletions with the old release before migration")
        if (
            "rag04_runs" in names
            and connection.execute("SELECT count(*) FROM rag04_runs").fetchone()[0]
            and not (chroma / "chroma.sqlite3").is_file()
        ):
            raise ValueError("Referenced Chroma data is missing; restore the paired store first")
        if "backend02_full_pair" in names:
            record = json.loads(
                connection.execute("SELECT data FROM backend02_full_pair WHERE id=1").fetchone()[0]
            )
            if json.loads((chroma / ".backend02-pair.json").read_text("utf-8")) != record:
                raise ValueError("Full-system SQLite/Chroma pair mismatch")
        if "rag04_store_binding" in names:
            record = connection.execute(
                "SELECT store_id FROM rag04_store_binding WHERE id=1"
            ).fetchone()
            if (
                record
                and json.loads((chroma / ".yk04-store.json").read_text("utf-8"))["store_id"]
                != record[0]
            ):
                raise ValueError("RAG SQLite/Chroma pair mismatch")
        destination.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect(destination / "app.db") as target:
            connection.backup(target)
    if chroma.exists():
        shutil.copytree(chroma, destination / "chroma")
    (destination / "backup.json").write_text(
        json.dumps(
            {
                "database_source": str(source),
                "chroma_source": str(chroma),
                "chroma_present": chroma.exists(),
                "created_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    first = sub.add_parser("bootstrap-admin")
    first.add_argument("--google-sub", required=True)
    claim = sub.add_parser("claim-legacy")
    claim.add_argument("--admin-sub", required=True)
    claim.add_argument("--owner-sub", required=True)
    migration = sub.add_parser("migrate")
    migration.add_argument("--backup-dir", type=Path, required=True)
    migration.add_argument("--workers-stopped", action="store_true", required=True)
    args = parser.parse_args()
    settings = Settings()
    database = Database(settings.database_url)
    try:
        if args.command == "migrate":
            paired_backup(settings, args.backup_dir)
            upgrade_database(database, allow_legacy=True)
        elif args.command == "bootstrap-admin":
            database.check_schema()
            bootstrap(database, args.google_sub)
        else:
            database.check_schema()
            claim_legacy(database, admin_sub=args.admin_sub, owner_sub=args.owner_sub)
        print("Operator action completed; no credentials were printed.")
    except Exception:
        parser.exit(
            2,
            "Operator action failed; verify account IDs, paired stores "
            "and fresh backup destination.\n",
        )
    finally:
        database.close()


if __name__ == "__main__":
    main()
