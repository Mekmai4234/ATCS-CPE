"""Persistent pair identity; paths can move together during a stopped backup/restore."""

import json
import os
from uuid import uuid4

import sqlalchemy as sa

from .errors import error
from .manifest import store_binding
from .vectors import ChromaStore

MARKER = ".yk04-store.json"


class StoreBinding:
    def __init__(self, manifest, path):
        self.manifest = manifest
        self.path = path.resolve()
        self.marker = self.path / MARKER

    def marker_id(self):
        try:
            data = json.loads(self.marker.read_text(encoding="utf-8"))
            value = data["store_id"]
            if data["version"] != 1 or not isinstance(value, str) or len(value) != 32:
                raise ValueError
            int(value, 16)
            return value
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            raise error(
                "index_store_mismatch", "Invalid Chroma pair marker; restore the paired backup"
            ) from None

    def check(self):
        identity = self.manifest.binding()
        if identity is None:
            return False
        if self.marker_id() != identity:
            raise error(
                "index_store_mismatch",
                "SQLite and Chroma do not match; select runtime env files or restore both together",
            )
        if not (self.path / "chroma.sqlite3").is_file() and any(
            row["state"] in {"published", "retired"} for row in self.manifest.all_runs()
        ):
            raise error(
                "index_store_mismatch", "Bound Chroma data is missing; restore the paired backup"
            )
        return True

    async def ensure(self, execution, *, create=False):
        execution.check()
        if self.check():
            return
        rows = self.manifest.all_runs()
        if rows or not create:
            raise error(
                "index_store_unbound",
                "Existing indexes require stopped maintenance: yk-rag init, then bind-store",
            )
        if self.marker_id() is not None:
            # Re-read under the SQLite writer lock: another first import may have
            # committed this same pair since check(), while a foreign marker must fail.
            self._bind(rows)
            return
        if (self.path / "chroma.sqlite3").is_file():
            store = ChromaStore(self.path, "yk04_preflight")
            try:
                if await store.call("has_data", execution.remaining_seconds):
                    raise error(
                        "index_store_mismatch", "Cannot pair a new database with populated Chroma"
                    )
            finally:
                await store.close()
        execution.check()
        self._bind(rows)

    async def adopt(self, execution):
        """Explicit legacy adoption: prove persisted published IDs before pairing."""
        execution.check()
        if self.check():
            return
        rows = self.manifest.all_runs()
        if not rows:
            await self.ensure(execution, create=True)
            return
        if not (self.path / "chroma.sqlite3").is_file():
            raise error("index_store_mismatch", "Legacy Chroma does not exist at the selected path")
        verified = False
        for row in rows:
            if row["state"] not in {"published", "retired"}:
                continue
            records = self.manifest.page([row["run_id"]], 0, row["chunk_count"] + 1)
            expected = {f"{row['run_id']}:{chunk.chunk_id}" for chunk in records}
            store = ChromaStore(self.path, row["collection"])
            try:
                actual = await store.call(
                    "get", execution.remaining_seconds, where={"run_id": row["run_id"]}, include=[]
                )
            finally:
                await store.close()
            if len(expected) != row["chunk_count"] or set(actual["ids"]) != expected:
                raise error(
                    "index_store_mismatch", "Legacy vector IDs do not match the SQLite manifest"
                )
            verified = verified or bool(expected)
        if not verified:
            raise error(
                "index_store_unbound",
                "No complete legacy run proves this pair; restore a known backup",
            )
        execution.check()
        self._bind(rows, adopt=True)

    def _bind(self, expected_rows, *, adopt=False):
        # SQLite serializes pair creation across processes. No await inside this transaction.
        with self.manifest.database.write() as connection:
            existing = connection.scalar(sa.select(store_binding.c.store_id))
            if existing is not None:
                if self.marker_id() != existing:
                    raise error(
                        "index_store_mismatch", "Concurrent store pairing selected another store"
                    )
                return
            if self.manifest.all_runs(connection) != expected_rows:
                raise error(
                    "source_changed", "Index changed during pairing; stop all writers and retry"
                )
            identity = self.marker_id()
            if identity is not None and not adopt:
                raise error("index_store_mismatch", "Chroma already has a pair marker")
            if identity is None:
                identity = uuid4().hex
                self.path.mkdir(parents=True, exist_ok=True)
                # Exclusive create never overwrites an identity. A crash before SQLite commit
                # fails closed; explicit legacy adoption can recover after validating all IDs.
                with self.marker.open("x", encoding="utf-8") as stream:
                    json.dump({"version": 1, "store_id": identity}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            connection.execute(store_binding.insert().values(id=1, store_id=identity))
