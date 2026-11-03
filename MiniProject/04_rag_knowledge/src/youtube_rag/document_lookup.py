"""Local substring retrieval with an inverted character index, never cloud embeddings.

Character grams only select candidates. A complete normalized query phrase must
occur in the text; matching Thai bigrams alone never becomes evidence.
"""

import re

import sqlalchemy as sa
from youtube_backend import database as db
from youtube_backend.document_store import normalize, read, snapshot
from youtube_backend.errors import AppError


def query_phrases(question):
    quoted = re.findall(r'["“](.+?)["”]', question)
    if quoted:
        return quoted[:16]
    question = re.sub(r"\d{1,}:\d{2}(?::\d{2})?", " ", question)
    question = re.sub(
        r"คำว่า|ประโยคที่ว่า|อยู่ตรงไหน|อยู่ช่วงไหน|ตรงไหน|คืออะไร|ค้นหา|ช่วยหา|ช่วยอธิบาย|อธิบาย|"
        r"ในคลิป|จากคลิป|ข้อความ|บทพูด|ช่วงเวลา|ช่วง|พูดอะไร|กล่าวถึงอะไร|"
        r"ให้หน่อย|หน่อย|ครับ|ค่ะ|คะ",
        " ",
        question,
    )
    value = normalize(question).strip(" ?!.,–-—")
    if value == "rag":
        return ["rag", "retrieval augmented", "generation"]
    return [value] if len(value) >= 2 else []


def search_connection(connection, documents, phrases, *, window=None, limit=6):
    if not 1 <= limit <= 30 or len(phrases) > 16 or any(len(p) > 2000 for p in phrases):
        raise AppError("invalid_query", "Document lookup budget exceeded", 422)
    phrases = list(dict.fromkeys(normalize(p) for p in phrases if normalize(p)))
    versions = [d["version"] for d in documents]
    table, grams = db.documents["passages"], db.documents["grams"]
    conditions = []
    for phrase in phrases:
        width = min(3, len(phrase))
        # All candidate tests are scoped by immutable version before reading text.
        keys = sorted({phrase[i : i + width] for i in range(len(phrase) - width + 1)})[:64]
        candidates = (
            sa.select(grams.c.version, grams.c.segment_id)
            .where(grams.c.version.in_(versions), grams.c.gram.in_(keys))
            .group_by(grams.c.version, grams.c.segment_id)
            .having(sa.func.count() == len(keys))
        )
        conditions.append(sa.tuple_(table.c.version, table.c.segment_id).in_(candidates))
    statement = sa.select(table).where(table.c.version.in_(versions))
    if window is None:
        if not conditions:
            return dict(
                items=[],
                candidates_examined=0,
                scan_complete=True,
                truncated=False,
                matched_ranges=[],
                provider_calls=0,
            )
        statement = statement.where(sa.or_(*conditions))
    rows = (
        connection.execute(statement.order_by(table.c.version, table.c.ordinal).limit(1001))
        .mappings()
        .all()
    )
    results = []
    by_version = {d["version"]: d for d in documents}
    for row in rows[:1000]:
        passage = row["data"]
        if window is not None:
            # Unknown ends cannot prove overlap with a closed requested interval.
            if passage["end_seconds"] is None or not (
                passage["end_seconds"] > window[0] and passage["start_seconds"] < window[1]
            ):
                continue
        elif not any(p in row["normalized"] for p in phrases):
            continue
        document = by_version[row["version"]]
        results.append(
            dict(
                **passage,
                video_id=document["video_id"],
                document_id=document["document_id"],
                document_version=row["version"],
                source_hash=document["source_hash"],
                title=document["data"]["relative_path"],
                timing_status=document["data"]["timing_status"],
            )
        )
    return dict(
        items=results[:limit],
        candidates_examined=min(len(rows), 1000),
        scan_complete=len(rows) <= 1000,
        truncated=len(results) > limit,
        matched_ranges=[
            dict(
                segment_id=r["segment_id"],
                start_seconds=r["start_seconds"],
                end_seconds=r["end_seconds"],
                line=r["line"],
            )
            for r in results[:limit]
        ],
        provider_calls=0,
    )


def lookup(context, sources, phrases, *, window=None, limit=6):
    documents = read(context, sources)
    with context.repository.db.read() as connection:
        result = search_connection(connection, documents, phrases, window=window, limit=limit)
    context.check()
    return dict(result, documents=documents)


def authorized_search(repo, scope, phrases, *, window=None, limit=6):
    with repo.db.read() as connection:
        sources = repo._sources(connection, scope)
        versions = snapshot(connection, sources)
        table = db.documents["versions"]
        documents = list(
            connection.execute(
                sa.select(table).where(table.c.version.in_(list(versions.values())))
            ).mappings()
        )
        result = search_connection(connection, documents, phrases, window=window, limit=limit)
        repo._check_sources(connection, sources)
    return dict(result, document_count=len(documents))
