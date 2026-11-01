import asyncio
import math
from uuid import uuid4

from youtube_backend.schemas import IndexReceipt, Source, TranscriptResult

from . import cursors
from .binding import StoreBinding
from .chunking import Chunker
from .embeddings import prepare_inputs, validate_vectors
from .errors import error
from .models import ChunkPage, CoverageInventory, SearchHit, digest
from .vectors import ChromaStore


def same_timestamp(value, expected):
    # Chroma's JSON round trip can turn 60.800000000000004 into 60.8. Permit
    # sub-nanosecond representation noise only; identifiers and scope stay exact.
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and math.isclose(value, expected, rel_tol=0, abs_tol=1e-9)
    )


class RagService:
    def __init__(self, settings, manifest, embedder, vectors=None):
        if embedder is not None and embedder.settings.fingerprint != settings.fingerprint:
            raise error("index_configuration_mismatch", "Embedder configuration does not match")
        self.settings = settings
        self.manifest = manifest
        self.embedder = embedder
        self.chunker = Chunker(settings)
        self.binding = StoreBinding(manifest, settings.chroma_persist_dir)
        self.vectors = vectors or ChromaStore(settings.chroma_persist_dir, settings.collection_name)

    def timeout(self, execution):
        execution.check()
        return min(self.settings.rag_operation_timeout_seconds, execution.remaining_seconds)

    def evidence_library(self):
        from .library import EvidenceLibrary

        return EvidenceLibrary(self)

    async def _embed(self, texts, execution, *, purpose="document", titles=None, cache_guard=None):
        timeout = self.timeout(execution)
        try:
            async with asyncio.timeout(timeout):
                if getattr(self.embedder, "requires_execution", False):
                    from .embedding_cache import EmbeddingCache

                    cache = EmbeddingCache(self.manifest.database, self.settings)
                    prepared = prepare_inputs(texts, purpose=purpose, titles=titles)
                    vectors = []

                    def guarded_scope():
                        scope = cache_guard() if cache_guard else None
                        if scope:
                            scope = {
                                **scope,
                                "model_policy": self.embedder.policy_identity(execution)
                                if callable(getattr(self.embedder, "policy_identity", None))
                                else execution.embedding_policy(
                                    self.settings.embedding_model,
                                    self.embedder.credential_sha256,
                                ),
                            }
                        return scope

                    for i, text in enumerate(texts):
                        scope = guarded_scope()
                        vector = cache.get(scope, prepared[i], purpose) if scope else None
                        if vector is None:
                            vector = (
                                await self.embedder.embed(
                                    [text],
                                    self.timeout(execution),
                                    purpose=purpose,
                                    titles=[titles[i]] if titles else None,
                                    execution=execution,
                                )
                            )[0]
                            if scope:
                                if guarded_scope() != scope:
                                    raise error("source_changed", "Embedding scope changed")
                                cache.put(scope, prepared[i], purpose, vector)
                        vectors.append(vector)
                else:
                    vectors = await self.embedder.embed(
                        texts, timeout, purpose=purpose, titles=titles
                    )
        except TimeoutError:
            raise error(
                "embedding_timeout",
                "Embedding request exceeded its deadline",
                retryable=True,
                status=504,
            ) from None
        execution.check()
        return validate_vectors(vectors, len(texts), self.settings.embedding_dimensions)

    def _snapshot(self, sources, execution, *, require=True, operation="read"):
        sources = [
            Source.model_validate(s.model_dump() if hasattr(s, "model_dump") else s)
            for s in sources
        ]
        execution.authorize(sources)
        permission = execution.permission_scope(sources, operation=operation)
        rows, missing = self.manifest.current(sources, self.settings.fingerprint, require=require)
        for row in rows:
            row["_permission"] = permission
        return sources, rows, missing

    def _recheck(self, sources, rows, execution, *, require=True, operation="read"):
        _, current, _ = self._snapshot(sources, execution, require=require, operation=operation)
        if [(r["run_id"], r["_permission"]) for r in current] != [
            (r["run_id"], r["_permission"]) for r in rows
        ]:
            raise error("source_changed", "Index changed while reading; restart this operation")

    async def index(
        self, source, transcript, execution, *, allow_reindex=False, preserve_previous=False
    ):
        source = Source.model_validate(source)
        transcript = TranscriptResult.model_validate(transcript)
        actual_version = digest(
            transcript.model_dump(
                mode="json", include={"video_id", "language", "source", "segments"}
            )
        )
        if actual_version != source.transcript_version:
            raise error("invalid_transcript", "Transcript content does not match its version")
        execution.authorize([source])
        execution.authorize_index(source, allow_reindex=allow_reindex)
        await self.binding.ensure(execution, create=True)
        try:
            current, _ = self.manifest.current([source], self.settings.fingerprint)
        except Exception as exc:
            if not allow_reindex or getattr(exc, "code", "") != "index_configuration_mismatch":
                raise
            current = []
        if current and not allow_reindex:
            previous = self.manifest.page([current[0]["run_id"]], 0, 1)
            expected_title = transcript.title or f"YouTube {source.video_id}"
            # 02's transcript hash excludes metadata. Gemini now embeds the title, so a
            # title-only update must replace the run even when transcript_version matches.
            allow_reindex = not previous or previous[0].title != expected_title
        if current and not allow_reindex:
            count = await self.inventory([source], execution)
            await self.cleanup(execution, source=source)
            return IndexReceipt(source=source, chunk_count=count, complete=True)
        records = await self.chunker.build_async(source, transcript, execution.check)
        run_id = uuid4().hex
        self.manifest.register(run_id, source, self.settings, len(records), execution)
        batch_size = self.settings.embedding_batch_size
        for offset in range(0, len(records), batch_size):
            batch = records[offset : offset + batch_size]
            vectors = await self._embed(
                [chunk.text for chunk in batch],
                execution,
                titles=[chunk.title for chunk in batch],
                cache_guard=lambda: execution.cache_scope([source]),
            )
            await self.vectors.call(
                "upsert",
                self.timeout(execution),
                ids=[f"{run_id}:{chunk.chunk_id}" for chunk in batch],
                embeddings=vectors,
                documents=[chunk.text for chunk in batch],
                metadatas=[
                    dict(
                        run_id=run_id,
                        chunk_id=chunk.chunk_id,
                        video_id=chunk.video_id,
                        generation=chunk.generation,
                        transcript_version=chunk.transcript_version,
                        start_seconds=chunk.start_seconds,
                        end_seconds=chunk.end_seconds,
                    )
                    for chunk in batch
                ],
            )
            execution.check()
        stored = await self.vectors.call(
            "get", self.timeout(execution), where={"run_id": run_id}, include=[]
        )
        expected_ids = {f"{run_id}:{chunk.chunk_id}" for chunk in records}
        if set(stored["ids"]) != expected_ids:
            raise error("incomplete_index", "Not all chunk vectors were persisted", status=502)
        await self.binding.ensure(execution)
        # No await between the atomic backend lease/lifecycle fence and publication.
        self.manifest.publish(run_id, source, records, execution)
        if not preserve_previous:
            await self.cleanup(execution, source=source)
        return IndexReceipt(source=source, chunk_count=len(records), complete=True)

    async def inventory(self, sources, execution):
        sources, rows, _ = self._snapshot(sources, execution, operation="inventory")
        await self.binding.ensure(execution)
        count = 0
        for row in rows:
            stored = await self.vectors.call(
                "get", self.timeout(execution), where={"run_id": row["run_id"]}, include=[]
            )
            records = self.manifest.page([row["run_id"]], 0, row["chunk_count"] + 1)
            expected = {f"{row['run_id']}:{chunk.chunk_id}" for chunk in records}
            if len(expected) != row["chunk_count"] or set(stored["ids"]) != expected:
                raise error(
                    "incomplete_index", "Published vector inventory is incomplete", status=502
                )
            count += len(stored["ids"])
        self._recheck(sources, rows, execution, operation="inventory")
        return count

    async def evidence(self, sources, chunk_ids, execution):
        if len(chunk_ids) > 1000:
            raise error("invalid_limit", "At most 1000 evidence IDs per request", status=422)
        sources, rows, _ = self._snapshot(sources, execution)
        await self.binding.ensure(execution)
        records = self.manifest.by_ids([row["run_id"] for row in rows], chunk_ids)
        self._recheck(sources, rows, execution)
        return [record.evidence() for record in records]

    async def short_context(self, sources, execution, *, max_bytes=16000, max_chunks=80):
        """Avoid a remote query embedding when the complete scoped clip fits locally.

        Uses the same version/grant-bound reader and cursor checks as full analysis.
        Returns None rather than silently selecting an arbitrary prefix of a long clip.
        """
        if not 1 <= max_bytes <= 24000 or not 1 <= max_chunks <= 100:
            raise error("invalid_limit", "Short context budget is outside its bounds", status=422)
        page = await self.read_video_chunks(sources, execution, limit=max_chunks)
        execution.check()
        if page.next_cursor or not page.inventory.complete:
            return None
        if sum(len(c.text.encode("utf-8")) + 512 for c in page.items) > max_bytes:
            return None
        return page.items

    async def select_context(self, question, sources, execution, *, limit=24, max_scan=256):
        """Bounded lexical + time-stratified candidates; no model/embedding dispatch."""
        from .library import terms

        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 12000
            or type(limit) is not int
            or not 1 <= limit <= 100
            or type(max_scan) is not int
            or not 1 <= max_scan <= 1000
        ):
            raise error("invalid_limit", "Provide a bounded evidence-selection query", status=422)
        sources, rows, _ = self._snapshot(sources, execution)
        await self.binding.ensure(execution)
        total = sum(row["chunk_count"] for row in rows)
        candidates = []
        if max_scan < len(rows):
            raise error("invalid_limit", "Scan budget must cover each selected source", status=422)
        remaining = max_scan
        for index, row in enumerate(rows):
            allocation = min(row["chunk_count"], max(1, remaining // (len(rows) - index)))
            offsets = (
                sorted(
                    {
                        round(i * (row["chunk_count"] - 1) / max(1, allocation - 1))
                        for i in range(allocation)
                    }
                )
                if row["chunk_count"]
                else []
            )
            for position in offsets:
                execution.check()
                candidates.extend(self.manifest.page([row["run_id"]], position, 1))
            remaining -= len(offsets)
            if remaining <= 0:
                break
        query = terms(question)
        scored = sorted(
            candidates,
            key=lambda chunk: (
                -len(query & terms(chunk.text)),
                chunk.video_id,
                chunk.start_seconds,
                chunk.chunk_id,
            ),
        )
        # Relevant matches come first; reserve half the slots for coverage across time/sources.
        selected = [chunk for chunk in scored if query & terms(chunk.text)][: max(1, limit // 2)]
        ordered = sorted(candidates, key=lambda chunk: (chunk.start_seconds, chunk.video_id))
        strata = (
            [
                ordered[round(i * (len(ordered) - 1) / max(1, limit - 1))]
                for i in range(min(limit, len(ordered)))
            ]
            if ordered
            else []
        )
        ids = {chunk.chunk_id for chunk in selected}
        for chunk in [*strata, *scored]:
            if len(selected) == limit:
                break
            if chunk.chunk_id not in ids:
                selected.append(chunk)
                ids.add(chunk.chunk_id)
        self._recheck(sources, rows, execution)
        return {
            "items": selected,
            "indexed_chunks": total,
            "inspected_chunks": len(candidates),
            "retrieved_chunks": len(selected),
            "scan_complete": len(candidates) == total,
            "selection": "lexical-time-stratified-v1",
            "model_calls": 0,
        }

    async def search(self, question, sources, execution, *, top_k=None, min_score=None):
        limit = self.settings.retrieval_top_k if top_k is None else top_k
        if type(limit) is not int or not 1 <= limit <= 100:
            raise error("invalid_limit", "top_k must be an integer from 1 to 100", status=422)
        if not isinstance(question, str) or not question.strip() or len(question) > 12000:
            raise error("invalid_question", "Question must contain 1-12000 characters", status=422)
        if self.chunker.count(question) > 7000:
            raise error("invalid_question", "Question exceeds embedding byte budget", status=422)
        if min_score is not None and (
            not isinstance(min_score, (int, float))
            or isinstance(min_score, bool)
            or not math.isfinite(min_score)
            or not -1 <= min_score <= 1
        ):
            raise error("invalid_limit", "min_score must be a finite cosine score", status=422)
        sources, rows, _ = self._snapshot(sources, execution)
        await self.binding.ensure(execution)
        query = (
            await self._embed(
                [question],
                execution,
                purpose="query",
                cache_guard=lambda: execution.cache_scope(sources),
            )
        )[0]
        run_ids = [r["run_id"] for r in rows]
        total = sum(r["chunk_count"] for r in rows)
        response = await self.vectors.call(
            "query",
            self.timeout(execution),
            query_embeddings=[query],
            n_results=min(total, limit * 4),
            where={"run_id": {"$in": run_ids}},
            include=["metadatas", "distances"],
        )
        try:
            candidates = list(
                zip(
                    response["ids"][0],
                    response["metadatas"][0],
                    response["distances"][0],
                    strict=True,
                )
            )
            if any(meta.get("run_id") not in run_ids for _, meta, _ in candidates):
                raise ValueError
            ids = [meta["chunk_id"] for _, meta, _ in candidates]
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            raise error(
                "incomplete_index",
                "Vector candidates exceed the authorized index snapshot",
                status=502,
            ) from None
        records = {c.chunk_id: c for c in self.manifest.by_ids(run_ids, ids)}
        owners = {row["run_id"]: row["source"] for row in rows}
        selected = []
        for vector_id, meta, distance in candidates:
            chunk = records.get(meta["chunk_id"])
            if (
                chunk is None
                or owners[meta["run_id"]]
                != {
                    "video_id": chunk.video_id,
                    "generation": chunk.generation,
                    "transcript_version": chunk.transcript_version,
                }
                or chunk.embedding_version != self.settings.fingerprint
                or vector_id != f"{meta['run_id']}:{chunk.chunk_id}"
                or any(
                    meta.get(field) != getattr(chunk, field)
                    for field in (
                        "video_id",
                        "generation",
                        "transcript_version",
                    )
                )
                or any(
                    not same_timestamp(meta.get(field), getattr(chunk, field))
                    for field in ("start_seconds", "end_seconds")
                )
                or not isinstance(distance, (int, float))
                or not math.isfinite(distance)
            ):
                raise error(
                    "incomplete_index", "Vector refers to missing chunk metadata", status=502
                )
            score = max(-1.0, min(1.0, 1.0 - distance))
            if min_score is not None and score < min_score:
                continue
            # Skip duplicate evidence windows introduced by caption overlap.
            duplicate = any(
                old.chunk.video_id == chunk.video_id
                and len(set(old.chunk.segment_ids) & set(chunk.segment_ids))
                / len(set(old.chunk.segment_ids) | set(chunk.segment_ids))
                >= 0.8
                and old.chunk.text == chunk.text
                for old in selected
            )
            if not duplicate:
                selected.append(SearchHit(chunk=chunk, ranking_score=score))
            if len(selected) == limit:
                break
        self._recheck(sources, rows, execution)
        return selected

    async def read_video_chunks(self, sources, execution, *, limit=100, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise error("invalid_limit", "Chunk page limit must be 1-200", status=422)
        sources, rows, missing = self._snapshot(sources, execution, require=False)
        await self.binding.ensure(execution)
        snapshot = digest(
            {
                "sources": [s.model_dump() for s in sources],
                "runs": [r["run_id"] for r in rows],
                "permission": execution.permission_scope(sources),
            }
        )
        offset = 0
        if cursor is not None:
            offset = cursors.decode(cursor, snapshot, self.manifest.cursor_key())
        total = sum(row["chunk_count"] for row in rows)
        items = self.manifest.page([r["run_id"] for r in rows], offset, limit)
        next_cursor = None
        if offset + len(items) < total:
            next_cursor = cursors.encode(snapshot, offset + len(items), self.manifest.cursor_key())
        self._recheck(sources, rows, execution, require=False)
        return ChunkPage(
            items=items,
            total=total,
            next_cursor=next_cursor,
            inventory=CoverageInventory(
                expected_videos=len(sources),
                available_videos=len(rows),
                expected_chunks=None if missing else total,
                available_chunks=total,
                missing_sources=missing,
                complete=not missing,
            ),
        )

    async def _remove_run(self, row, execution):
        await self.binding.ensure(execution)
        self.manifest.check_removal(row, execution)
        store = self.vectors
        own = row["collection"] != self.settings.collection_name
        if own:
            store = ChromaStore(self.settings.chroma_persist_dir, row["collection"])
        try:
            await store.call("delete", self.timeout(execution), where={"run_id": row["run_id"]})
            remaining = await store.call(
                "get", self.timeout(execution), where={"run_id": row["run_id"]}, include=[]
            )
            if remaining["ids"]:
                raise error(
                    "incomplete_cleanup",
                    "Vectors remain; cleanup metadata retained",
                    retryable=True,
                )
            await self.binding.ensure(execution)
            self.manifest.forget(row["run_id"], execution)
        finally:
            if own:
                await store.close()

    async def cleanup(self, execution, *, source=None, include_staging=False):
        execution.authorize_cleanup(source=source, include_staging=include_staging)
        await self.binding.ensure(execution)
        await self.media.cleanup(execution, source=source, include_staging=include_staging)
        # include_staging is only for explicit maintenance with all workers stopped.
        for row in self.manifest.garbage(include_staging=include_staging):
            if source is not None and (
                row["video_id"] != source.video_id or row["generation"] != source.generation
            ):
                continue
            try:
                await self._remove_run(row, execution)
            except Exception as exc:
                if (
                    source is None
                    or row["state"] != "retired"
                    or getattr(exc, "code", None) != "source_in_use"
                ):
                    raise
                # A published replacement is valid; defer obsolete vectors until readers finish.

    @property
    def media(self):
        if not hasattr(self, "_media"):
            from .media import MediaRag

            self._media = MediaRag(self)
        return self._media

    async def delete(self, video_id, generation, execution):
        execution.check()
        await self.binding.ensure(execution, create=not self.manifest.all_runs())
        await self.media.delete(video_id, generation, execution)
        for row in self.manifest.begin_delete(video_id, generation, execution):
            await self._remove_run(row, execution)

    async def close(self):
        if hasattr(self, "_media"):
            await self._media.close()
        await self.vectors.close()
        if self.embedder is not None:
            await self.embedder.close()
