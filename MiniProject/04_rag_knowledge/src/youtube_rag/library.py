"""Bounded local evidence catalogue over immutable, separately typed source stores.

Ranking is lexical, not a confidence score. It makes no model/embedding requests.
Consumers must judge sufficiency before generating an answer or requesting more video.
"""

import math
import re
import time
from typing import Literal

import sqlalchemy as sa
from pydantic import Field
from youtube_backend import database as db
from youtube_backend.repository import digest, row
from youtube_backend.schemas import Citation, Schema, Source
from youtube_backend.video_evidence import VERSION, VideoEvidenceStore, verify_video_citation

from .errors import error
from .manifest import BackendExecution, chunks
from .models import Chunk


class LibraryRecord(Schema):
    evidence_id: str
    kind: Literal["transcript", "ocr", "visual", "video"]
    source: Source
    evidence_version: str
    text: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    citation: dict
    provenance: dict
    ranking_score: float = 0


class LibraryResult(Schema):
    items: list[LibraryRecord]
    inspected_records: int
    complete: bool
    notes: list[str]


def terms(text):
    words = set(re.findall(r"[^\W_]+", text.casefold()))
    # Thai has no required word spaces; index character bigrams as well as words.
    for word in list(words):
        if re.search(r"[\u0e00-\u0e7f]", word):
            words.update(word[i : i + 2] for i in range(len(word) - 1))
    return words


def overlaps(start, end, lower, upper):
    """Positive overlap with [lower, upper); point observations include only their instant."""
    if start == end:
        return (lower is None or start >= lower) and (upper is None or start < upper)
    return (lower is None or end > lower) and (upper is None or start < upper)


class EvidenceLibrary:
    def __init__(self, rag):
        self.rag = rag

    async def search(
        self,
        question,
        sources,
        context,
        *,
        kinds=None,
        limit=12,
        start_seconds=None,
        end_seconds=None,
        neighbors=0,
        max_records=1000,
    ):
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 12000
            or type(limit) is not int
            or not 1 <= limit <= 100
            or type(max_records) is not int
            or not 1 <= max_records <= 5000
            or type(neighbors) is not int
            or not 0 <= neighbors <= 2
        ):
            raise error("invalid_scope", "Provide a bounded evidence query")
        kinds = set(kinds if kinds is not None else ("transcript", "ocr", "visual", "video"))
        if not kinds or not kinds <= {"transcript", "ocr", "visual", "video"}:
            raise error("invalid_scope", "Unknown evidence kind")
        for value in (start_seconds, end_seconds):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value < 0
            ):
                raise error("invalid_scope", "Invalid evidence time range")
        if start_seconds is not None and end_seconds is not None and start_seconds >= end_seconds:
            raise error("invalid_scope", "Evidence range must be ordered")
        sources = [
            Source.model_validate(s.model_dump() if hasattr(s, "model_dump") else s)
            for s in sources
        ]
        execution = BackendExecution(context)
        execution.authorize(sources)
        if max_records < len(sources):
            raise error("invalid_scope", "Record budget must cover every selected source")
        if not context.settings.auth_enabled:
            raise error("authentication_required", "Evidence library requires a member", status=401)
        records, complete = [], True
        # Equal per-source collection bounds prevent one long clip hiding other clips.
        per_source = max(1, max_records // len(sources))
        for source in sources:
            if "transcript" in kinds:
                items, bounded = await self._transcript(
                    question,
                    source,
                    execution,
                    min(200, max(1, per_source // len(kinds))),
                    start_seconds,
                    end_seconds,
                    neighbors,
                )
                for chunk in items:
                    citation = Citation(
                        citation_id=chunk.chunk_id,
                        chunk_id=chunk.chunk_id,
                        video_id=chunk.video_id,
                        title=chunk.title,
                        start_seconds=chunk.start_seconds,
                        end_seconds=chunk.end_seconds,
                        url=f"https://www.youtube.com/watch?v={chunk.video_id}&t={int(chunk.start_seconds)}s",
                    )
                    records.append(
                        LibraryRecord(
                            evidence_id=chunk.chunk_id,
                            kind="transcript",
                            source=source,
                            evidence_version=source.transcript_version,
                            text=chunk.text,
                            start_seconds=chunk.start_seconds,
                            end_seconds=chunk.end_seconds,
                            citation=citation.model_dump(),
                            provenance={
                                "segment_ids": chunk.segment_ids,
                                "embedding_version": chunk.embedding_version,
                                "ordinal": chunk.ordinal,
                            },
                        )
                    )
                complete = complete and bounded
            remaining = per_source - sum(r.source == source for r in records)
            if kinds - {"transcript"}:
                if remaining:
                    local, bounded = self._local(source, context, kinds, remaining)
                    records.extend(local)
                    complete = complete and bounded
                else:
                    complete = False
        query = terms(question)
        scored = []
        for record in records:
            if not overlaps(record.start_seconds, record.end_seconds, start_seconds, end_seconds):
                continue
            overlap = query & terms(record.text)
            if overlap:
                scored.append(
                    record.model_copy(update={"ranking_score": len(overlap) / len(query)})
                )
        groups = {
            s.video_id: sorted(
                [r for r in scored if r.source == s],
                key=lambda r: (-r.ranking_score, r.start_seconds, r.evidence_id),
            )
            for s in sources
        }
        selected = []
        while len(selected) < limit and any(groups.values()):
            for group in groups.values():
                if group and len(selected) < limit:
                    selected.append(group.pop(0))
        if neighbors:
            for hit in list(selected):
                nearby = sorted(
                    [r for r in records if r.source == hit.source and r.kind == hit.kind],
                    key=lambda r: (r.start_seconds, r.evidence_id),
                )
                index = next(i for i, r in enumerate(nearby) if r.evidence_id == hit.evidence_id)
                for record in nearby[max(0, index - neighbors) : index + neighbors + 1]:
                    if len(selected) >= limit:
                        break
                    if not overlaps(
                        record.start_seconds, record.end_seconds, start_seconds, end_seconds
                    ):
                        continue
                    if not any(
                        r.evidence_id == record.evidence_id
                        and r.source == record.source
                        and r.kind == record.kind
                        for r in selected
                    ):
                        selected.append(record)
        execution.authorize(sources)
        return LibraryResult(
            items=selected,
            inspected_records=len(records),
            complete=complete,
            notes=[
                "Lexical relevance only; sampled observations do not establish exhaustive coverage."
            ]
            + (
                [
                    "Time filter uses positive overlap with [start, end); citations retain their "
                    "full original intervals and may extend beyond the requested window."
                ]
                if start_seconds is not None or end_seconds is not None
                else []
            )
            + (
                []
                if complete
                else [
                    "Collection bound reached or source inventory incomplete; "
                    "absence is not proof of missing content."
                ]
            ),
        )

    async def _transcript(self, question, source, execution, limit, start, end, neighbors):
        # Filter the existing immutable chunk index BEFORE applying the collection
        # bound, so a late relevant interval is not hidden by an unrelated prefix.
        sources, rows, missing = self.rag._snapshot([source], execution, require=False)
        await self.rag.binding.ensure(execution)
        tokens = sorted(terms(question), key=lambda word: (-len(word), word))
        conditions = [chunks.c.run_id.in_([r["run_id"] for r in rows])]
        conditions.append(
            sa.or_(
                *(
                    chunks.c.data["text"].as_string().icontains(t, autoescape=True)
                    for t in tokens[:24]
                )
            )
        )
        if start is not None:
            conditions.append(chunks.c.data["end_seconds"].as_float() > start)
        if end is not None:
            conditions.append(chunks.c.data["start_seconds"].as_float() < end)
        with self.rag.manifest.database.read() as c:
            raw = (
                c.execute(
                    sa.select(chunks.c.data)
                    .where(*conditions)
                    .order_by(chunks.c.ordinal)
                    .limit(limit + 1)
                )
                .scalars()
                .all()
            )
        complete = not missing and len(raw) <= limit and len(tokens) <= 24
        selected = {value["chunk_id"]: Chunk.model_validate(value) for value in raw[:limit]}
        if neighbors:
            for chunk in list(selected.values()):
                for adjacent in self.rag.manifest.page(
                    [r["run_id"] for r in rows],
                    max(0, chunk.ordinal - neighbors),
                    2 * neighbors + 1,
                ):
                    if not overlaps(adjacent.start_seconds, adjacent.end_seconds, start, end):
                        continue
                    if adjacent.chunk_id not in selected:
                        if len(selected) == limit:
                            complete = False
                            break
                        selected[adjacent.chunk_id] = adjacent
        self.rag._recheck(sources, rows, execution, require=False)
        return list(selected.values()), complete

    def _local(self, source, context, kinds, limit):
        result, complete = [], True
        store = VideoEvidenceStore(context)
        with context.repository.db.read() as c:
            job = store.guard(c, source)
            if "video" in kinds:
                table = db.v2["cache"]
                rows = (
                    c.execute(
                        sa.select(table)
                        .where(
                            table.c.owner_id == job["owner_id"],
                            table.c.video_id == source.video_id,
                            table.c.generation == source.generation,
                            table.c.evidence_version == source.transcript_version,
                            table.c.prompt_version == VERSION,
                            table.c.model
                            == (context.settings.vision_model or context.settings.llm_model),
                            table.c.expires_at > time.time(),
                        )
                        .order_by(table.c.expires_at.desc(), table.c.cache_id)
                        .limit(min(64, limit) + 1)
                    )
                    .mappings()
                    .all()
                )
                complete = len(rows) <= min(64, limit)
                seen = set()
                for record in rows[: min(64, limit)]:
                    for observation in record["data"].get("observations", []):
                        cid = digest(observation)
                        if cid in seen:
                            continue
                        if len(result) >= limit:
                            complete = False
                            break
                        citation = Citation(
                            citation_id=cid,
                            chunk_id=cid,
                            video_id=source.video_id,
                            title=observation["text"][:160],
                            start_seconds=observation["start_seconds"],
                            end_seconds=observation["end_seconds"],
                            kind="video",
                            observation_cache_id=record["cache_id"],
                            url=f"https://www.youtube.com/watch?v={source.video_id}&t={int(observation['start_seconds'])}s",
                        )
                        checked = verify_video_citation(context.repository, c, job, citation)
                        result.append(
                            LibraryRecord(
                                evidence_id=cid,
                                kind="video",
                                source=source,
                                evidence_version=record["cache_id"],
                                text=checked["text"],
                                start_seconds=citation.start_seconds,
                                end_seconds=citation.end_seconds,
                                citation=citation.model_dump(),
                                provenance={
                                    "model": record["model"],
                                    "prompt_version": record["prompt_version"],
                                    "observation_kind": checked["kind"],
                                    "coverage": record["data"].get("coverage", {}),
                                    "reuse_expires_at": record["expires_at"],
                                },
                            )
                        )
                        seen.add(cid)
            if kinds & {"ocr", "visual"}:
                state = row(
                    c,
                    db.v2["media_states"],
                    sa.and_(
                        db.v2["media_states"].c.video_id == source.video_id,
                        db.v2["media_states"].c.generation == source.generation,
                    ),
                )
                for snapshot in ((state or {}).get("data") or {}).get("snapshots", []):
                    if (
                        snapshot.get("video_id") != source.video_id
                        or snapshot.get("generation") != source.generation
                    ):
                        raise error("source_changed", "Media snapshot exceeds selected source")
                    if snapshot["kind"] not in kinds:
                        continue
                    revision = row(
                        c, db.v2["revisions"], db.v2["revisions"].c.revision_id == digest(snapshot)
                    )
                    if not revision:
                        raise error("source_changed", "Current media revision is missing")
                    for item in revision["data"]["items"]:
                        if len(result) >= limit:
                            complete = False
                            break
                        from youtube_backend.evidence_v2 import VisualCitationV2

                        citation = VisualCitationV2(
                            source=snapshot,
                            frame_id=item["frame_id"],
                            asset_id=item["asset_id"],
                            start_seconds=item["timestamp_seconds"],
                            text=item["text"],
                            asset_url=item["asset_url"],
                        )
                        result.append(
                            LibraryRecord(
                                evidence_id=digest(citation.model_dump()),
                                kind=snapshot["kind"],
                                source=source,
                                evidence_version=snapshot["evidence_version"],
                                text=item["text"],
                                start_seconds=item["timestamp_seconds"],
                                end_seconds=item["timestamp_seconds"],
                                citation=citation.model_dump(),
                                provenance={
                                    "snapshot": snapshot,
                                    "coverage": revision["data"]["coverage"],
                                },
                            )
                        )
            store.guard(c, source)
        return result, complete
