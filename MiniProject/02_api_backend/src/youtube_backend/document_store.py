"""Trusted local publication and authorized immutable document reads."""

import hashlib
import json
import unicodedata

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert

from . import database as db
from .errors import AppError
from .urls import canonical_url

POLICY = "document-lexical-nfc-substring-v1"


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def ngrams(text):
    return {text[i : i + size] for size in (1, 2, 3) for i in range(len(text) - size + 1)}


def publish(database, document):
    """Local operator only. Validate/index/activate in one BEGIN IMMEDIATE transaction."""
    segments = document["segments"]
    if not segments or len({s["segment_id"] for s in segments}) != len(segments):
        raise ValueError("Invalid document segment identities")
    for i, segment in enumerate(segments):
        start, end = segment["start_seconds"], segment["end_seconds"]
        if not segment["text"].strip() or start < 0 or (end is not None and end <= start):
            raise ValueError("Invalid document interval/text")
        if end is None and i != len(segments) - 1:
            raise ValueError("Only the final document segment may have unknown end")
    versions, active, passages, grams = (
        db.documents[k] for k in ("versions", "active", "passages", "grams")
    )
    video_id = document["video_id"]
    with database.write() as c:
        video = (
            c.execute(sa.select(db.videos).where(db.videos.c.video_id == video_id))
            .mappings()
            .first()
        )
        if not video or video["status"] != "ready":
            raise AppError(
                "video_not_ready", "Document mapping requires an existing ready clip", 409
            )
        identity = [POLICY, document, video["generation"], video["indexed_version"]]
        version = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        exists = c.scalar(sa.select(versions.c.version).where(versions.c.version == version))
        if not exists:
            c.execute(
                versions.insert().values(
                    version=version,
                    document_id=document["document_id"],
                    video_id=video_id,
                    generation=video["generation"],
                    transcript_version=video["indexed_version"],
                    source_hash=document["sha256"],
                    data={k: v for k, v in document.items() if k != "segments"},
                )
            )
            for i, segment in enumerate(segments):
                text = normalize(segment["text"])
                c.execute(
                    passages.insert().values(
                        version=version,
                        segment_id=segment["segment_id"],
                        ordinal=i,
                        normalized=text,
                        data=segment,
                    )
                )
                c.execute(
                    grams.insert(),
                    [
                        dict(gram=g, version=version, segment_id=segment["segment_id"])
                        for g in sorted(ngrams(text))
                    ],
                )
        count = c.scalar(
            sa.select(sa.func.count()).select_from(passages).where(passages.c.version == version)
        )
        if count != len(segments):
            raise AppError("incomplete_index", "Document index receipt differs from source", 409)
        current = c.scalar(sa.select(active.c.version).where(active.c.video_id == video_id))
        if exists and current and current != version:
            return dict(
                version=version,
                imported=False,
                activated=False,
                indexed_segments=count,
                reason="historical_version_requires_explicit_rollback",
            )
        c.execute(
            insert(active)
            .values(video_id=video_id, version=version)
            .on_conflict_do_update(index_elements=[active.c.video_id], set_={"version": version})
        )
    return dict(version=version, imported=not bool(exists), activated=True, indexed_segments=count)


def snapshot(c, sources):
    versions, active = db.documents["versions"], db.documents["active"]
    result = {}
    for source in sources:
        record = (
            c.execute(
                sa.select(versions)
                .join(active, active.c.version == versions.c.version)
                .where(
                    active.c.video_id == source["video_id"],
                    versions.c.generation == source["generation"],
                    versions.c.transcript_version == source["transcript_version"],
                )
            )
            .mappings()
            .first()
        )
        if record:
            result[source["video_id"]] = record["version"]
    return result


def check_snapshot(c, job):
    expected = job["payload"].get("document_sources")
    if expected is not None and snapshot(c, job["payload"].get("sources", [])) != expected:
        raise AppError("source_changed", "Document version changed; submit a new task", 409)


def read(context, sources):
    context.check()
    context.authorize_sources(sources)
    with context.repository.db.read() as c:
        job = context.repository._owned(c, context.job_id, context.lease_token)
        check_snapshot(c, job)
        wanted = {s.video_id for s in sources}
        versions = db.documents["versions"]
        return [
            dict(r)
            for r in c.execute(
                sa.select(versions).where(
                    versions.c.version.in_(
                        list(job["payload"].get("document_sources", {}).values())
                    ),
                    versions.c.video_id.in_(wanted),
                )
            ).mappings()
        ]


def verify_citation(repo, c, job, citation):
    versions, passages = db.documents["versions"], db.documents["passages"]
    check_snapshot(c, job)
    if (
        job["payload"].get("document_sources", {}).get(citation.video_id)
        != citation.document_version
    ):
        raise AppError("invalid_citation", "Document citation is outside frozen sources", 502)
    document = (
        c.execute(sa.select(versions).where(versions.c.version == citation.document_version))
        .mappings()
        .first()
    )
    if (
        not document
        or document["source_hash"] != citation.source_hash
        or document["document_id"] != citation.document_id
    ):
        raise AppError("invalid_citation", "Document identity mismatch", 502)
    data = document["data"]
    if citation.kind == "document_metadata":
        if (
            citation.chunk_id != "metadata:" + citation.metadata_field
            or citation.metadata_field not in data["metadata"]
        ):
            raise AppError("invalid_citation", "Unknown document metadata field", 502)
    else:
        passage = c.scalar(
            sa.select(passages.c.data).where(
                passages.c.version == citation.document_version,
                passages.c.segment_id == citation.chunk_id,
            )
        )
        if not passage or (passage["start_seconds"], passage["end_seconds"], passage["line"]) != (
            citation.start_seconds,
            citation.end_seconds,
            citation.document_line,
        ):
            raise AppError("invalid_citation", "Document passage identity/time mismatch", 502)
    citation.title = data["relative_path"]
    citation.url = canonical_url(citation.video_id)
    if citation.start_seconds is not None:
        citation.url += f"&t={int(citation.start_seconds)}s"


def source_page(repo, video_id, version=None, limit=50, offset=0):
    versions, passages = db.documents["versions"], db.documents["passages"]
    with repo.db.read() as c:
        sources = repo._sources(c, {"video_ids": [video_id]})
        version = version or snapshot(c, sources).get(video_id)
        source = sources[0]
        record = (
            c.execute(
                sa.select(versions).where(
                    versions.c.version == version,
                    versions.c.video_id == video_id,
                    versions.c.generation == source["generation"],
                    versions.c.transcript_version == source["transcript_version"],
                )
            )
            .mappings()
            .first()
        )
        if not record:
            raise AppError("document_not_found", "Document version is unavailable", 404)
        items = list(
            c.scalars(
                sa.select(passages.c.data)
                .where(passages.c.version == version)
                .order_by(passages.c.ordinal)
                .offset(offset)
                .limit(limit)
            )
        )
        count = c.scalar(
            sa.select(sa.func.count()).select_from(passages).where(passages.c.version == version)
        )
        return dict(
            document_id=record["document_id"],
            version=version,
            source_hash=record["source_hash"],
            title=record["data"]["relative_path"],
            metadata=record["data"]["metadata"],
            timing_status=record["data"]["timing_status"],
            items=items,
            total=count,
            limit=limit,
            offset=offset,
        )
