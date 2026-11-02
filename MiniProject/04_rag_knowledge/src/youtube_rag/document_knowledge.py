"""The same frozen document passages for answer, analysis and learning tools."""

import sqlalchemy as sa
from youtube_backend import database as db
from youtube_backend.document_store import read

from . import cursors
from .document_lookup import lookup, query_phrases
from .manifest import security
from .models import Chunk, ChunkPage, CoverageInventory, SearchHit, digest


def chunk(document, passage, source, ordinal=0):
    return Chunk(
        chunk_id=passage["segment_id"],
        video_id=source.video_id,
        transcript_version=source.transcript_version,
        title=document["data"]["relative_path"],
        text=passage["text"],
        start_seconds=passage["start_seconds"],
        end_seconds=passage["end_seconds"],
        generation=source.generation,
        embedding_version="local-document-v1",
        segment_ids=[passage["segment_id"]],
        ordinal=ordinal,
        token_count=max(1, len(passage["text"].encode())),
        canonical_url=f"https://www.youtube.com/watch?v={source.video_id}",
        document_citation=dict(
            kind="document_transcript",
            document_id=document["document_id"],
            document_version=document["version"],
            source_hash=document["source_hash"],
            document_line=passage["line"],
        ),
    )


def page(context, sources, *, limit=100, cursor=None):
    documents = read(context, sources)
    if not documents:
        return None
    table = db.documents["passages"]
    by_version = {d["version"]: d for d in documents}
    source_map = {s.video_id: s for s in sources}
    identity = digest(
        ["document-page-v1", context.user_id, [[d["video_id"], d["version"]] for d in documents]]
    )
    with context.repository.db.read() as c:
        key = c.scalar(sa.select(security.c.cursor_key).where(security.c.id == 1)).encode()
        offset = cursors.decode(cursor, identity, key) if cursor else 0
        count = c.scalar(
            sa.select(sa.func.count()).select_from(table).where(table.c.version.in_(by_version))
        )
        rows = (
            c.execute(
                sa.select(table)
                .where(table.c.version.in_(by_version))
                .order_by(table.c.version, table.c.ordinal)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
    items = [
        chunk(
            by_version[r["version"]],
            r["data"],
            source_map[by_version[r["version"]]["video_id"]],
            r["ordinal"],
        )
        for r in rows
    ]
    missing = [s for s in sources if s.video_id not in {d["video_id"] for d in documents}]
    context.check()
    return ChunkPage(
        items=items,
        total=count,
        next_cursor=cursors.encode(identity, offset + len(items), key)
        if offset + len(items) < count
        else None,
        inventory=CoverageInventory(
            expected_videos=len(sources),
            available_videos=len(documents),
            expected_chunks=count,
            available_chunks=count,
            missing_sources=missing,
            complete=not missing,
        ),
    )


def evidence(context, sources, ids):
    documents = read(context, sources)
    if not documents:
        return None
    table = db.documents["passages"]
    by_version = {d["version"]: d for d in documents}
    source_map = {s.video_id: s for s in sources}
    with context.repository.db.read() as c:
        rows = (
            c.execute(
                sa.select(table).where(table.c.version.in_(by_version), table.c.segment_id.in_(ids))
            )
            .mappings()
            .all()
        )
    context.check()
    return [
        chunk(
            by_version[r["version"]],
            r["data"],
            source_map[by_version[r["version"]]["video_id"]],
            r["ordinal"],
        ).evidence()
        for r in rows
    ]


def search(context, sources, query, *, top_k=8, **kwargs):
    result = lookup(context, sources, query_phrases(query), limit=top_k)
    if not result["documents"]:
        return None
    documents = {d["version"]: d for d in result["documents"]}
    source_map = {s.video_id: s for s in sources}
    return [
        SearchHit(
            chunk=chunk(documents[p["document_version"]], p, source_map[p["video_id"]]),
            ranking_score=1,
        )
        for p in result["items"]
    ]
