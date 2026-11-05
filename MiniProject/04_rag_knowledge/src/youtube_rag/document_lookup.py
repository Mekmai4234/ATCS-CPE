"""Local substring retrieval with an inverted character index, never cloud embeddings.

Character grams only select candidates. In `lookup` a complete normalized query
phrase must occur in the text. `related` is the separate, explicitly labelled
fallback for plain-language questions: it ranks real transcript lines by
keyword/character-trigram overlap, and callers must present them as "related",
never as an exact match.
"""

import math
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


# Question phrasing, not topic: removed before ranking related passages.
QUESTION_WORDS = re.compile(
    r"อยู่ตรงไหน|อยู่ช่วงไหน|ตรงไหน|ช่วงไหน|ตอนไหน|คืออะไร|คืออย่างไร|คือยังไง|หมายถึงอะไร|"
    r"ย่อมาจากอะไร|อย่างไร|ยังไง|อะไรบ้าง|อะไร|ทำไม|เท่าไหร่|เท่าไร|กี่|หรือเปล่า|"
    r"หรือไม่|ค้นหา|ช่วยหา|ช่วยบอก|บอกหน่อย|ช่วยอธิบาย|อธิบาย|คำว่า|ประโยคที่ว่า|"
    r"ในคลิปนี้|ในคลิป|จากคลิป|คลิปนี้|วิดีโอนี้|ข้อความ|บทพูด|ช่วงเวลา|พูดถึง|พูดว่า|พูดอะไร|"
    r"กล่าวถึง|เกี่ยวกับ|เรื่อง|มีการ|ให้หน่อย|หน่อย|"
    # Short particles only at a word end, so "คะแนน" or "ไหม้" stay intact.
    r"(?:ไหม|มั้ย|บ้าง|เหรอ|หรอ|ครับ|คับ|ค่ะ|คะ|นะ|จ้า)(?=[\s?!.ๆ]|$)|"
    r"\b(?:what|how|why|where|when|which|who|is|are|does|do|the|a|an|about|in|this|video|"
    r"clip|explain|tell|me)\b"
)
# Speakers write English terms in Thai script; either spelling finds both.
ALIASES = (
    ("rag", "แร็ก", "แคก"),
    ("search", "เสิร์ช", "สิร์ช", "เซิร์ช"),
    ("keyword", "คีย์เวิร์ด"),
    ("vector", "เวกเตอร์"),
    ("llm", "แอลแอลเอ็ม"),
    ("chatbot", "แชทบอท"),
    ("embedding", "embedded", "เอ็มเบด"),
    ("semantic", "ซีแมนติก"),
    ("database", "ดาต้าเบส"),
    ("prompt", "พรอมต์", "พร้อมท์"),
    ("gpt", "จีพีที"),
    ("upload", "อัปโหลด", "อัพโหลด"),
    ("card", "การ์ด"),
    ("gacha", "กาชา"),
)
ALIAS_PATTERN = re.compile(
    "|".join(sorted({re.escape(a) for group in ALIASES for a in group}, key=len, reverse=True))
)
RELATED_MIN_SCORE = 0.55
RELATED_MAX_PASSAGES = 5000


def related_terms(question):
    """Topic terms: ("exact", spellings) must occur whole; ("grams", trigrams) may match partly."""
    text = re.sub(r"\d{1,}:\d{2}(?::\d{2})?", " ", question)
    text = normalize(QUESTION_WORDS.sub(" ", normalize(text)))
    text = ALIAS_PATTERN.sub(lambda m: " " + m.group(0) + " ", text)
    terms = []
    for token in re.findall(r"[0-9a-z][0-9a-z,.\-]*|[฀-๿]+", text):
        if len(token) < 2:
            continue
        group = next((g for g in ALIASES if token in g), None)
        if group or re.match(r"[0-9a-z]", token):
            terms.append(("exact", frozenset(group or (token,))))
        else:
            grams = {token[i : i + 3] for i in range(len(token) - 2)} or {token}
            terms.append(("grams", frozenset(grams)))
    return terms


def _rank_document(rows, terms, limit):
    """Score each line with its neighbours; the score is the weighted share of terms found."""
    lines = [row["normalized"] for row in rows]
    count = len(lines)
    weighted = []
    for kind, items in terms:
        if kind == "exact":
            # Topic words (English terms and their Thai spellings) count double.
            weighted.append((kind, items, None, 2.0))
        else:
            idf = {
                k: math.log((count + 1) / (sum(k in line for line in lines) + 0.5)) for k in items
            }
            # Short Thai fragments ("วัน", "ได้") carry less meaning than longer phrases.
            size = max(len(k) for k in items) + len(items) - 1
            weighted.append((kind, items, idf, min(1.0, size / 5)))
    total = sum(item[3] for item in weighted)

    def score(text):
        value = 0.0
        for kind, items, idf, weight in weighted:
            if kind == "exact":
                value += weight if any(a in text for a in items) else 0.0
            else:
                value += weight * sum(v for k, v in idf.items() if k in text) / sum(idf.values())
        return value / total

    scored = sorted(
        (
            (score(" ".join(lines[max(0, i - 1) : i + 2])), score(lines[i]), -i)
            for i in range(count)
        ),
        reverse=True,
    )
    if not scored or scored[0][0] < RELATED_MIN_SCORE:
        return []
    cutoff = max(RELATED_MIN_SCORE, scored[0][0] * 0.75)
    picked, used, seen = [], set(), set()
    for value, _, negative in scored:
        i = -negative
        if value < cutoff or len(picked) >= limit:
            break
        if i in used or lines[i] in seen:
            continue
        group = [j for j in range(max(0, i - 1), min(count, i + 2)) if j not in used]
        used.update(range(i - 1, i + 2))
        seen.add(lines[i])
        picked.append((value, [rows[j] for j in group]))
    return picked


def related_connection(connection, documents, question, *, window=None, limit=3):
    if not 1 <= limit <= 10:
        raise AppError("invalid_query", "Document lookup budget exceeded", 422)
    terms = related_terms(question)
    if not terms or not documents:
        return dict(groups=[], provider_calls=0)
    table = db.documents["passages"]
    rows = (
        connection.execute(
            sa.select(table)
            .where(table.c.version.in_([d["version"] for d in documents]))
            .order_by(table.c.version, table.c.ordinal)
            .limit(RELATED_MAX_PASSAGES + 1)
        )
        .mappings()
        .all()
    )
    by_version = {d["version"]: d for d in documents}
    candidates = []
    for version in by_version:
        passages = [r for r in rows[:RELATED_MAX_PASSAGES] if r["version"] == version]
        if window is not None:
            # Unknown ends cannot prove overlap with a closed requested interval.
            passages = [
                r
                for r in passages
                if r["data"]["end_seconds"] is not None
                and r["data"]["end_seconds"] > window[0]
                and r["data"]["start_seconds"] < window[1]
            ]
        candidates += [
            (value, version, group) for value, group in _rank_document(passages, terms, limit)
        ]
    candidates.sort(key=lambda item: item[0], reverse=True)
    groups = []
    for value, version, group in candidates[:limit]:
        document = by_version[version]
        groups.append(
            dict(
                score=round(value, 3),
                items=[
                    dict(
                        **row["data"],
                        video_id=document["video_id"],
                        document_id=document["document_id"],
                        document_version=version,
                        source_hash=document["source_hash"],
                        title=document["data"]["relative_path"],
                        timing_status=document["data"]["timing_status"],
                    )
                    for row in group
                ],
            )
        )
    return dict(groups=groups, truncated=len(rows) > RELATED_MAX_PASSAGES, provider_calls=0)


def related(context, sources, question, *, window=None, limit=3):
    documents = read(context, sources)
    with context.repository.db.read() as connection:
        result = related_connection(connection, documents, question, window=window, limit=limit)
    context.check()
    return result
