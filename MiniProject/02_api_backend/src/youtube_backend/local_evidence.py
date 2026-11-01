"""Bounded transcript excerpts from the existing authorized store; no AI requests."""

import re

import sqlalchemy as sa
from pydantic import Field

from . import database as db
from .errors import AppError
from .schemas import Schema, Scope
from .urls import canonical_url


class LocalEvidenceRequest(Schema):
    question: str = Field(min_length=1, max_length=2000)
    scope: Scope


def search(repo, request):
    # Lexical excerpts are not generated answers or proof of semantic absence.
    terms = set(re.findall(r"[^\W_]+", request.question.casefold()))
    for word in list(terms):
        if re.search(r"[\u0e00-\u0e7f]", word):
            terms.update(word[i : i + 2] for i in range(len(word) - 1))
    terms = sorted(terms)[:64]
    items, inspected, scanned = [], 0, []
    with repo.db.read() as c:
        owner = repo._actor(c)
        sources = repo._sources(c, request.scope.model_dump(mode="json"))
        if len(sources) > 10:
            raise AppError("invalid_scope", "Search at most ten selected clips", 422)
        for source in sources:
            rows = (
                c.execute(
                    sa.select(db.segments)
                    .where(
                        db.segments.c.video_id == source["video_id"],
                        db.segments.c.version == source["transcript_version"],
                    )
                    .order_by(db.segments.c.position)
                    .limit(1001)
                )
                .mappings()
                .all()
            )
            inspected += min(len(rows), 1000)
            scanned.append(len(rows) <= 1000)
            candidates = []
            for row in rows[:1000]:
                score = sum(term in row["text"].casefold() for term in terms)
                if not score:
                    continue
                candidates.append((score, row))
            for _, row in sorted(candidates, key=lambda item: (-item[0], item[1]["position"]))[:3]:
                items.append(
                    dict(
                        video_id=source["video_id"],
                        text=row["text"][:4000],
                        text_truncated=len(row["text"]) > 4000,
                        start_seconds=row["start_seconds"],
                        end_seconds=row["start_seconds"] + row["duration_seconds"],
                        transcript_version=source["transcript_version"],
                        url=canonical_url(source["video_id"]) + f"&t={int(row['start_seconds'])}s",
                    )
                )
        repo._check_sources(c, sources, owner=owner)
    return dict(
        items=items,
        inspected_segments=inspected,
        scan_complete=all(scanned),
        provider_calls=0,
        kind="transcript_excerpts",
        notice="ข้อความที่ตรงคำค้นจากบทถอดเสียง ไม่ใช่คำตอบที่ AI สร้าง และไม่ยืนยันว่าไม่มีข้อมูลเมื่อค้นไม่พบ",
    )
