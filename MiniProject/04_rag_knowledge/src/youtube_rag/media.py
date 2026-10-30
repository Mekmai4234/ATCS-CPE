"""Execution-bound OCR/visual retrieval using 02 PR #27's enrichment scope.

No public multi-source chat scope is invented here. Every storage/cache/vector
path is fenced by the durable 02 lease, actor, generation and current revision.
"""

import math
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert
from youtube_backend import database as db
from youtube_backend.evidence_v2 import SourceSnapshotV2, VisualCitationV2
from youtube_backend.repository import digest as backend_digest

from .embedding_cache import EmbeddingCache
from .errors import error
from .media_manifest import media_active as active
from .media_manifest import media_chunks as chunks
from .media_manifest import media_runs as runs
from .models import digest
from .vectors import ChromaStore


class MediaRag:
    def __init__(self, rag):
        self.rag = rag
        self.database = rag.manifest.database
        self.fingerprint = digest(
            ["media-text-v3", "media-part-v1", 6000, rag.settings.fingerprint]
        )
        self.collection = f"yk04_media_v3_{self.fingerprint[:24]}"
        self.vectors = ChromaStore(rag.settings.chroma_persist_dir, self.collection)

    def guard(self, c, snapshot, execution):
        ctx = execution.context
        if not ctx.settings.auth_enabled:
            raise error("authentication_required", "Media retrieval requires a member", status=401)
        job = ctx.repository._owned(c, ctx.job_id, ctx.lease_token)
        execution.check()
        if (
            job["kind"] != "enrich"
            or job["video_id"] != snapshot.video_id
            or job["generation"] != snapshot.generation
        ):
            raise error("invalid_scope", "Media exceeds the durable enrichment scope", status=403)
        ctx.repository._require_video(c, snapshot.video_id, job["owner_id"])
        video = (
            c.execute(sa.select(db.videos).where(db.videos.c.video_id == snapshot.video_id))
            .mappings()
            .first()
        )
        if (
            not video
            or video["generation"] != snapshot.generation
            or video["status"] in {"deleting", "deleted"}
        ):
            raise error("source_changed", "Media generation changed")
        table = db.v2["media_states"]
        state = (
            c.execute(
                sa.select(table).where(
                    table.c.video_id == snapshot.video_id, table.c.generation == snapshot.generation
                )
            )
            .mappings()
            .first()
        )
        if (
            not state
            or not state["data"]
            or snapshot.model_dump() not in state["data"].get("snapshots", [])
        ):
            raise error("source_changed", "Media evidence revision changed")
        table = db.v2["revisions"]
        revision = (
            c.execute(
                sa.select(table).where(table.c.revision_id == backend_digest(snapshot.model_dump()))
            )
            .mappings()
            .first()
        )
        if not revision:
            raise error("source_changed", "Media revision is missing")
        return job, revision["data"]

    def scope(self, snapshots, execution):
        result = []
        with self.database.read() as c:
            for snapshot in snapshots:
                job, _ = self.guard(c, snapshot, execution)
                result.append(snapshot.model_dump())
        return {"owner": job["owner_id"], "sources": result}

    @staticmethod
    def snapshots(values):
        items = [SourceSnapshotV2.model_validate(v) for v in values]
        if (
            not items
            or len(items) > 2
            or any(s.kind == "transcript" for s in items)
            or len({s.kind for s in items}) != len(items)
        ):
            raise error("invalid_scope", "Use distinct OCR/visual snapshots; transcript uses v1")
        return items

    def record(self, snapshot, item):
        citation = VisualCitationV2(
            source=snapshot,
            frame_id=item["frame_id"],
            asset_id=item["asset_id"],
            start_seconds=item["timestamp_seconds"],
            text=item["text"],
            asset_url=item["asset_url"],
        )
        return {"evidence_id": digest(citation.model_dump()), "citation": citation.model_dump()}

    @staticmethod
    def parts(records):
        result = []
        for record in records:
            text, current, size = record["citation"]["text"], [], 0
            pieces = []
            for char in text:
                count = len(char.encode("utf-8"))
                if size + count > 6000:
                    pieces.append("".join(current))
                    current, size = [], 0
                current.append(char)
                size += count
            if current:
                pieces.append("".join(current))
            for index, piece in enumerate(pieces):
                result.append(
                    {
                        "evidence_id": record["evidence_id"],
                        "text": piece,
                        "part_id": digest(["media-part-v1", record["evidence_id"], index, piece]),
                    }
                )
        return result

    def local(self, snapshot, execution):
        with self.database.read() as c:
            _, data = self.guard(c, snapshot, execution)
        return [self.record(snapshot, item) for item in data["items"]], data["coverage"]

    async def index(self, value, execution, *, semantic=True):
        snapshot = self.snapshots([value])[0]
        records, coverage = self.local(snapshot, execution)
        if not records:
            raise error("index_incomplete", "No prepared media text")
        # Persist independently complete local evidence before optional Gemini work.
        lexical_id = digest(["lexical-v3", snapshot.model_dump()])
        with self.database.write() as c:
            self.guard(c, snapshot, execution)
            # A newer prepared revision invalidates the former semantic pointer,
            # even while its replacement waits for quota. Other kinds stay separate.
            old = list(
                c.execute(
                    sa.select(runs).where(
                        runs.c.video_id == snapshot.video_id,
                        runs.c.generation == snapshot.generation,
                        runs.c.state.in_(["lexical", "published"]),
                    )
                ).mappings()
            )
            for row in old:
                if (
                    row["snapshot"]["kind"] == snapshot.kind
                    and row["snapshot"] != snapshot.model_dump()
                ):
                    c.execute(
                        runs.update().where(runs.c.run_id == row["run_id"]).values(state="retired")
                    )
                    c.execute(active.delete().where(active.c.run_id == row["run_id"]))
            c.execute(
                insert(runs)
                .values(
                    run_id=lexical_id,
                    video_id=snapshot.video_id,
                    generation=snapshot.generation,
                    snapshot=snapshot.model_dump(),
                    config="lexical-v3",
                    collection=self.collection,
                    state="lexical",
                    count=len(records),
                )
                .on_conflict_do_nothing()
            )
            for record in records:
                c.execute(
                    insert(chunks)
                    .values(
                        run_id=lexical_id,
                        evidence_id=record["evidence_id"],
                        text=record["citation"]["text"],
                        data=record,
                    )
                    .on_conflict_do_nothing()
                )
            self.guard(c, snapshot, execution)
        if not semantic:
            return self.receipt(snapshot, len(records), False, coverage)
        await self.rag.binding.ensure(execution, create=True)
        parts = self.parts(records)
        run_id = uuid4().hex
        with self.database.write() as c:
            self.guard(c, snapshot, execution)
            c.execute(
                runs.insert().values(
                    run_id=run_id,
                    video_id=snapshot.video_id,
                    generation=snapshot.generation,
                    snapshot=snapshot.model_dump(),
                    config=self.fingerprint,
                    collection=self.collection,
                    state="staging",
                    count=len(parts),
                )
            )
        # Cache each successful item before the next dispatch. A denied call stops
        # immediately; resume reuses checkpoints without extracting/OCRing again.
        for record in parts:
            text = record["text"]
            vector = (
                await self.rag._embed(
                    [text],
                    execution,
                    titles=[f"{snapshot.kind} {snapshot.video_id}"],
                    cache_guard=lambda: self.scope([snapshot], execution),
                )
            )[0]
            await self.vectors.call(
                "upsert",
                self.rag.timeout(execution),
                ids=[f"{run_id}:{record['part_id']}"],
                embeddings=[vector],
                documents=[text],
                metadatas=[
                    {
                        "run_id": run_id,
                        "evidence_id": record["evidence_id"],
                        "part_id": record["part_id"],
                    }
                ],
            )
            self.scope([snapshot], execution)
        stored = await self.vectors.call(
            "get", self.rag.timeout(execution), where={"run_id": run_id}, include=[]
        )
        if set(stored["ids"]) != {f"{run_id}:{r['part_id']}" for r in parts}:
            raise error("index_incomplete", "Media vectors were not fully persisted")
        with self.database.write() as c:
            self.guard(c, snapshot, execution)
            prior = c.scalar(
                sa.select(active.c.run_id).where(
                    active.c.video_id == snapshot.video_id,
                    active.c.generation == snapshot.generation,
                    active.c.kind == snapshot.kind,
                )
            )
            if prior:
                c.execute(runs.update().where(runs.c.run_id == prior).values(state="retired"))
            for record in records:
                c.execute(
                    chunks.insert().values(
                        run_id=run_id,
                        evidence_id=record["evidence_id"],
                        text=record["citation"]["text"],
                        data=record,
                    )
                )
            c.execute(runs.update().where(runs.c.run_id == run_id).values(state="published"))
            c.execute(
                insert(active)
                .values(
                    video_id=snapshot.video_id,
                    generation=snapshot.generation,
                    kind=snapshot.kind,
                    run_id=run_id,
                )
                .on_conflict_do_update(
                    index_elements=[active.c.video_id, active.c.generation, active.c.kind],
                    set_={"run_id": run_id},
                )
            )
            self.guard(c, snapshot, execution)
        return self.receipt(snapshot, len(records), True, coverage)

    @staticmethod
    def receipt(snapshot, count, semantic, coverage):
        return {
            "snapshot": snapshot.model_dump(),
            "prepared_evidence_complete": True,
            "evidence_count": count,
            "semantic_ready": semantic,
            "whole_video_reviewed": False,
            "sampled_timestamps": coverage["sampled_timestamps"],
            "duration_seconds": coverage["duration_seconds"],
            "unassessed_kinds": [k for k in ("transcript", "ocr", "visual") if k != snapshot.kind],
            "coverage_limitation": "Prepared samples only; unsampled intervals were not reviewed",
        }

    async def evidence(self, values, evidence_ids, execution):
        snapshots = self.snapshots(values)
        if len(evidence_ids) > 1000:
            raise error("invalid_limit", "At most 1000 evidence IDs", status=422)
        self.scope(snapshots, execution)
        result = []
        for snapshot in snapshots:
            records, _ = self.local(snapshot, execution)
            result.extend(r for r in records if r["evidence_id"] in evidence_ids)
        self.scope(snapshots, execution)
        return result

    async def inventory(self, values, execution):
        snapshots = self.snapshots(values)
        self.scope(snapshots, execution)
        result = []
        for snapshot in snapshots:
            records, coverage = self.local(snapshot, execution)
            with self.database.read() as c:
                self.guard(c, snapshot, execution)
                row = (
                    c.execute(
                        sa.select(runs)
                        .join(active, runs.c.run_id == active.c.run_id)
                        .where(
                            active.c.video_id == snapshot.video_id,
                            active.c.generation == snapshot.generation,
                            active.c.kind == snapshot.kind,
                        )
                    )
                    .mappings()
                    .first()
                )
            semantic = bool(
                row
                and row["snapshot"] == snapshot.model_dump()
                and row["config"] == self.fingerprint
                and row["state"] == "published"
            )
            if semantic:
                await self.rag.binding.ensure(execution)
                actual = await self.vectors.call(
                    "get", self.rag.timeout(execution), where={"run_id": row["run_id"]}, include=[]
                )
                if set(actual["ids"]) != {
                    f"{row['run_id']}:{r['part_id']}" for r in self.parts(records)
                }:
                    raise error(
                        "incomplete_index", "Published media vector inventory is incomplete"
                    )
            result.append(self.receipt(snapshot, len(records), semantic, coverage))
        self.scope(snapshots, execution)
        return result

    async def search(self, question, values, execution, *, mode="auto", top_k=8):
        snapshots = self.snapshots(values)
        if (
            mode not in {"auto", "lexical", "semantic"}
            or type(top_k) is not int
            or not 1 <= top_k <= 100
        ):
            raise error("invalid_limit", "Invalid media search options", status=422)
        if not isinstance(question, str) or not question.strip() or len(question) > 12000:
            raise error("invalid_question", "Provide a bounded nonempty question", status=422)
        self.scope(snapshots, execution)
        rows = []
        with self.database.read() as c:
            for snapshot in snapshots:
                self.guard(c, snapshot, execution)
                row = (
                    c.execute(
                        sa.select(runs)
                        .join(active, runs.c.run_id == active.c.run_id)
                        .where(
                            active.c.video_id == snapshot.video_id,
                            active.c.generation == snapshot.generation,
                            active.c.kind == snapshot.kind,
                        )
                    )
                    .mappings()
                    .first()
                )
                if (
                    row
                    and row["snapshot"] == snapshot.model_dump()
                    and row["config"] == self.fingerprint
                    and row["state"] == "published"
                ):
                    rows.append(dict(row))
        fallback = None
        if mode != "lexical" and len(rows) == len(snapshots):
            try:
                result = await self.semantic(question, snapshots, rows, execution, top_k)
                self.scope(snapshots, execution)
                return {
                    "mode": "semantic",
                    "hits": result,
                    "semantic_complete": True,
                    "whole_video_reviewed": False,
                    "limitation": "Prepared samples only",
                }
            except Exception as exc:
                # Permission/integrity/lifecycle failures NEVER become empty/fallback results.
                if mode != "auto" or getattr(exc, "code", "") not in {
                    "quota_wait",
                    "free_tier_unverified",
                    "free_model_unverified",
                    "provider_rate_limited",
                    "provider_unavailable",
                    "provider_timeout",
                    "gemini_broker_required",
                    "embedding_unavailable",
                }:
                    raise
                fallback = exc.code
        elif mode == "semantic":
            raise error("index_incomplete", "Media semantic index is not ready")
        else:
            fallback = "semantic_index_pending" if mode != "lexical" else None
        hits = []
        # SQLite instr treats the query literally (no FTS syntax/wildcard injection),
        # including Thai substrings. It is deliberately NOT semantic retrieval.
        with self.database.read() as c:
            for snapshot in snapshots:
                self.guard(c, snapshot, execution)
                run_id = digest(["lexical-v3", snapshot.model_dump()])
                records = c.execute(
                    sa.select(chunks.c.data)
                    .where(
                        chunks.c.run_id == run_id,
                        sa.func.instr(sa.func.lower(chunks.c.text), question.strip().lower()) > 0,
                    )
                    .order_by(chunks.c.evidence_id)
                    .limit(top_k)
                ).scalars()
                hits.extend({**r, "ranking_score": 1.0} for r in records)
            for snapshot in snapshots:
                self.guard(c, snapshot, execution)
        return {
            "mode": "lexical",
            "hits": hits[:top_k],
            "semantic_complete": False,
            "fallback_reason": fallback,
            "whole_video_reviewed": False,
            "limitation": "Literal text in prepared samples only; semantic search is unavailable",
        }

    async def semantic(self, question, snapshots, rows, execution, top_k):
        await self.rag.binding.ensure(execution)
        vector = (
            await self.rag._embed(
                [question],
                execution,
                purpose="query",
                cache_guard=lambda: self.scope(snapshots, execution),
            )
        )[0]
        ids = [r["run_id"] for r in rows]
        response = await self.vectors.call(
            "query",
            self.rag.timeout(execution),
            query_embeddings=[vector],
            n_results=min(sum(r["count"] for r in rows), top_k * 4),
            where={"run_id": {"$in": ids}},
            include=["metadatas", "distances"],
        )
        expected = {}
        expected_parts = {}
        for snapshot in snapshots:
            records, _ = self.local(snapshot, execution)
            for record in records:
                expected[record["evidence_id"]] = record
            expected_parts.update({p["part_id"]: p["evidence_id"] for p in self.parts(records)})
        hits = []
        try:
            for vid, meta, distance in zip(
                response["ids"][0], response["metadatas"][0], response["distances"][0], strict=True
            ):
                record = expected[meta["evidence_id"]]
                if (
                    meta["run_id"] not in ids
                    or vid != f"{meta['run_id']}:{meta['part_id']}"
                    or expected_parts[meta["part_id"]] != record["evidence_id"]
                    or not isinstance(distance, (int, float))
                    or not math.isfinite(distance)
                ):
                    raise ValueError
                owner = next(r for r in rows if r["run_id"] == meta["run_id"])
                if owner["snapshot"] != record["citation"]["source"]:
                    raise ValueError
                if not any(hit["evidence_id"] == record["evidence_id"] for hit in hits):
                    hits.append({**record, "ranking_score": max(-1.0, min(1.0, 1 - distance))})
        except (KeyError, TypeError, ValueError, IndexError, StopIteration):
            raise error(
                "incomplete_index", "Media vector candidates failed snapshot validation", status=502
            ) from None
        # Reindex during an await invalidates the original active run snapshot.
        with self.database.read() as c:
            for row in rows:
                if not c.scalar(sa.select(active.c.run_id).where(active.c.run_id == row["run_id"])):
                    raise error("source_changed", "Media index changed while reading")
        return hits[:top_k]

    async def cleanup(self, execution, *, source=None, include_staging=False):
        execution.authorize_cleanup(source=source, include_staging=include_staging)
        states = ["retired"] + (["staging"] if include_staging else [])
        with self.database.read() as c:
            selected = list(c.execute(sa.select(runs).where(runs.c.state.in_(states))).mappings())
        for row in selected:
            if source is not None and (
                row["video_id"] != source.video_id or row["generation"] != source.generation
            ):
                continue
            with self.database.write() as c:
                if c.scalar(sa.select(active.c.run_id).where(active.c.run_id == row["run_id"])):
                    raise error("active_index", "Cannot remove an active media run")
                self.rag.manifest._removal_guard(c, row, execution)
            store = ChromaStore(self.rag.settings.chroma_persist_dir, row["collection"])
            try:
                await store.call(
                    "delete", self.rag.timeout(execution), where={"run_id": row["run_id"]}
                )
                remaining = await store.call(
                    "get", self.rag.timeout(execution), where={"run_id": row["run_id"]}, include=[]
                )
                if remaining["ids"]:
                    raise error("incomplete_cleanup", "Media vectors remain")
            finally:
                await store.close()
            with self.database.write() as c:
                self.rag.manifest._removal_guard(c, row, execution)
                c.execute(chunks.delete().where(chunks.c.run_id == row["run_id"]))
                c.execute(runs.delete().where(runs.c.run_id == row["run_id"]))

    async def delete(self, video_id, generation, execution):
        # Existing 04 deletion fence requires the actual 02 deleting tombstone,
        # zero memberships and no live readers before any physical deletion.
        from youtube_backend.schemas import Source

        source = Source(video_id=video_id, generation=generation, transcript_version="delete")
        with self.database.write() as c:
            execution.fence(c, source, delete=True)
            selected = list(
                c.execute(
                    sa.select(runs).where(
                        runs.c.video_id == video_id, runs.c.generation <= generation
                    )
                ).mappings()
            )
            c.execute(
                active.delete().where(
                    active.c.video_id == video_id, active.c.generation <= generation
                )
            )
            c.execute(
                runs.update()
                .where(runs.c.video_id == video_id, runs.c.generation <= generation)
                .values(state="deleting")
            )
        for row in selected:
            store = ChromaStore(self.rag.settings.chroma_persist_dir, row["collection"])
            try:
                await store.call(
                    "delete", self.rag.timeout(execution), where={"run_id": row["run_id"]}
                )
                remaining = await store.call(
                    "get", self.rag.timeout(execution), where={"run_id": row["run_id"]}, include=[]
                )
                if remaining["ids"]:
                    raise error("incomplete_cleanup", "Media vectors remain; metadata retained")
            finally:
                await store.close()
            with self.database.write() as c:
                execution.fence(c, source, delete=True)
                c.execute(chunks.delete().where(chunks.c.run_id == row["run_id"]))
                c.execute(runs.delete().where(runs.c.run_id == row["run_id"]))
        with self.database.write() as c:
            execution.fence(c, source, delete=True)
            EmbeddingCache.purge(c, video_id, generation)

    async def close(self):
        await self.vectors.close()
