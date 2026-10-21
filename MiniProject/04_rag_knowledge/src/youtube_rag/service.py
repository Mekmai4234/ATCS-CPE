import asyncio
import base64
import json
import math
from uuid import uuid4

from youtube_backend.schemas import IndexReceipt, Source, TranscriptResult

from .binding import StoreBinding
from .chunking import Chunker
from .embeddings import validate_vectors
from .errors import error
from .models import ChunkPage, CoverageInventory, SearchHit, digest
from .vectors import ChromaStore


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

    async def _embed(self, texts, execution, *, purpose="document", titles=None):
        timeout = self.timeout(execution)
        try:
            async with asyncio.timeout(timeout):
                vectors = await self.embedder.embed(texts, timeout, purpose=purpose, titles=titles)
        except TimeoutError:
            raise error(
                "embedding_timeout",
                "Embedding request exceeded its deadline",
                retryable=True,
                status=504,
            ) from None
        execution.check()
        return validate_vectors(vectors, len(texts), self.settings.embedding_dimensions)

    def _snapshot(self, sources, execution, *, require=True):
        sources = [
            Source.model_validate(s.model_dump() if hasattr(s, "model_dump") else s)
            for s in sources
        ]
        execution.authorize(sources)
        rows, missing = self.manifest.current(sources, self.settings.fingerprint, require=require)
        return sources, rows, missing

    def _recheck(self, sources, rows, execution, *, require=True):
        _, current, _ = self._snapshot(sources, execution, require=require)
        if [r["run_id"] for r in current] != [r["run_id"] for r in rows]:
            raise error("source_changed", "Index changed while reading; restart this operation")

    async def index(self, source, transcript, execution, *, allow_reindex=False):
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
                [chunk.text for chunk in batch], execution, titles=[chunk.title for chunk in batch]
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
        await self.cleanup(execution, source=source)
        return IndexReceipt(source=source, chunk_count=len(records), complete=True)

    async def inventory(self, sources, execution):
        sources, rows, _ = self._snapshot(sources, execution)
        await self.binding.ensure(execution)
        count = 0
        for row in rows:
            stored = await self.vectors.call(
                "get", self.timeout(execution), where={"run_id": row["run_id"]}, include=[]
            )
            if len(stored["ids"]) != row["chunk_count"]:
                raise error(
                    "incomplete_index", "Published vector inventory is incomplete", status=502
                )
            count += len(stored["ids"])
        self._recheck(sources, rows, execution)
        return count

    async def evidence(self, sources, chunk_ids, execution):
        if len(chunk_ids) > 1000:
            raise error("invalid_limit", "At most 1000 evidence IDs per request", status=422)
        sources, rows, _ = self._snapshot(sources, execution)
        await self.binding.ensure(execution)
        records = self.manifest.by_ids([row["run_id"] for row in rows], chunk_ids)
        self._recheck(sources, rows, execution)
        return [record.evidence() for record in records]

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
        query = (await self._embed([question], execution, purpose="query"))[0]
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
        ids = [meta["chunk_id"] for meta in response["metadatas"][0]]
        records = {c.chunk_id: c for c in self.manifest.by_ids(run_ids, ids)}
        selected = []
        for chunk_id, distance in zip(ids, response["distances"][0], strict=True):
            chunk = records.get(chunk_id)
            if chunk is None:
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
        snapshot = digest([s.model_dump() for s in sources] + [r["run_id"] for r in rows])
        offset = 0
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 1000:
                    raise ValueError
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                offset = decoded["offset"]
                if decoded["snapshot"] != snapshot or type(offset) is not int or offset < 0:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise error(
                    "invalid_cursor", "Cursor is invalid or its index has changed", status=422
                ) from None
        total = sum(row["chunk_count"] for row in rows)
        items = self.manifest.page([r["run_id"] for r in rows], offset, limit)
        next_cursor = None
        if offset + len(items) < total:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps({"snapshot": snapshot, "offset": offset + len(items)}).encode()
            ).decode()
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
            self.manifest.forget(row["run_id"])
        finally:
            if own:
                await store.close()

    async def cleanup(self, execution, *, source=None, include_staging=False):
        await self.binding.ensure(execution)
        # include_staging is only for explicit maintenance with all workers stopped.
        for row in self.manifest.garbage(include_staging=include_staging):
            if source is not None and (
                row["video_id"] != source.video_id or row["generation"] != source.generation
            ):
                continue
            await self._remove_run(row, execution)

    async def delete(self, video_id, generation, execution):
        execution.check()
        await self.binding.ensure(execution, create=not self.manifest.all_runs())
        for row in self.manifest.begin_delete(video_id, generation, execution):
            await self._remove_run(row, execution)

    async def close(self):
        await self.vectors.close()
        if self.embedder is not None:
            await self.embedder.close()
