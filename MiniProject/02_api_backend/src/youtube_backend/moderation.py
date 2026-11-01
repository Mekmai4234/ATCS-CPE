"""Versioned local rules, bounded normalization and server-bound acknowledgements.

This is an application policy, not a semantic classifier. Original text is never rewritten.
"""

import hashlib
import re
import secrets
import time
import unicodedata

import sqlalchemy as sa

from . import database as db
from .errors import AppError
from .repository import digest, row, uid

POLICY_VERSION = "chat-local-v1"
MAX_POLICY_CHARACTERS = 128000
NEUTRAL_ANSWER = "คำตอบนี้ถูกระงับ กรุณาปรับคำถามหรือลองถามจากหลักฐานในคลิปอีกครั้ง"
WARNING = "ข้อความนี้อาจไม่เหมาะสม ลองปรับคำก่อนส่ง"
BLOCKED = "กรุณาปรับข้อความให้เหมาะสมก่อนส่งอีกครั้ง"


def normalize(text):
    text = "".join(
        c
        for c in unicodedata.normalize("NFKC", text[:MAX_POLICY_CHARACTERS])
        if unicodedata.category(c) != "Cf"
    ).casefold()
    # NFKC expands Thai SARA AM; keep its spelling equivalent without deleting marks.
    text = text.replace("\u0e4d\u0e32", "\u0e33")
    text = re.sub(r"\bf\s+u\s+c\s+k\b", "fuck", text)
    return re.sub(r"\s+", " ", text).strip()


def classify(text):
    if len(text) > MAX_POLICY_CHARACTERS:
        return "block", "policy_length_limit"
    value = normalize(text)
    # Quoted study material is exempt only inside actual paired quotes; abuse
    # outside those quotes still runs through the same rules.
    if re.search(r"meaning|translate|quoted|ความหมาย|แปลว่า|หมายความว่า|คำว่า", value):
        value = re.sub(r"""["“][^"“”\n]{1,500}["”]|'[^'\n]{1,500}'""", " ", value)
    if re.search(
        r"\bi (?:will|am going to) kill you\b|กูจะฆ่ามึง|มึง\s*(?:มัน|แม่ง)?\s*(?:โง่|ควาย)|"
        r"\byou(?:'re| are) (?:a |an )?(?:fucking )?(?:i{1,4}d{1,4}i{1,4}o{1,4}t{1,4}|moron)\b",
        value,
    ):
        return "block", "direct_abuse"
    if re.search(
        r"ignore (?:all |the )?(?:previous |system )?instructions|ข้ามกฎ|ไม่ต้องทำตามกฎ", value
    ):
        return "warn", "rule_bypass_suspected"
    if re.search(r"\b(?:fuck(?:ing)?|shit|damn)\b|แม่ง(?!ู)|ไอ้เหี้ย", value):
        return "warn", "possibly_inappropriate"
    return "allow", "none"


def request_digest(request):
    return digest(
        {
            k: v
            for k, v in request.items()
            if k != "moderation_token" and not (k == "mode" and v == "video")
        }
    )


def add_event(
    repo,
    c,
    *,
    owner,
    direction,
    action,
    reason,
    content,
    job_id=None,
    message_id=None,
    request_hash=None,
    token_hash=None,
    expires_at=None,
    conversation_id=None,
):
    now, event_id = time.time(), uid()
    c.execute(
        db.review["events"]
        .insert()
        .values(
            event_id=event_id,
            conversation_id=conversation_id,
            owner_id=owner,
            direction=direction,
            action=action,
            reason=reason,
            content=content,
            job_id=job_id,
            message_id=message_id,
            policy_version=POLICY_VERSION,
            request_hash=request_hash,
            token_hash=token_hash,
            expires_at=expires_at,
            content_expires_at=now + repo.settings.moderation_retention_days * 86400,
            created_at=now,
        )
    )
    if action in {"block", "withhold"}:
        c.execute(
            db.review["cases"]
            .insert()
            .values(
                case_id=uid(),
                owner_id=owner,
                message_id=message_id,
                event_id=event_id,
                source="system",
                label=reason,
                status="new",
                notes="",
                created_at=now,
                updated_at=now,
            )
        )
    return event_id


def precheck(repo, request):
    decision, reason = classify(request["question"])
    token = secrets.token_urlsafe(32) if decision == "warn" else None
    event_id = None
    if decision != "allow":
        with repo.db.write() as c:
            owner = repo._actor(c)
            if request.get("conversation_id"):
                conversation = row(
                    c,
                    db.conversations,
                    db.conversations.c.conversation_id == request["conversation_id"],
                )
                repo._private(c, conversation)
                if not conversation:
                    raise AppError("not_found", "Conversation not found", 404)
            event_id = add_event(
                repo,
                c,
                owner=owner,
                direction="input",
                action=decision,
                reason=reason,
                content=request["question"],
                request_hash=request_digest(request),
                token_hash=hashlib.sha256(token.encode()).hexdigest() if token else None,
                expires_at=time.time() + 300 if token else None,
                conversation_id=request.get("conversation_id"),
            )
    return dict(
        decision=decision,
        reason=reason,
        policy_version=POLICY_VERSION,
        message=BLOCKED if decision == "block" else WARNING if decision == "warn" else "",
        attempt_id=event_id,
        acknowledgment_token=token,
        expires_in=300 if token else None,
    )


def admit(repo, request):
    """Validate a ticket for NEW work; do not mutate it or publish an execution proof."""
    decision, reason = classify(request["question"])
    if decision == "allow":
        return None
    if decision == "warn" and request.get("moderation_token"):
        with repo.db.read() as c:
            owner = repo._actor(c)
            table = db.review["events"]
            event = row(
                c,
                table,
                sa.and_(
                    table.c.owner_id == owner,
                    table.c.direction == "input",
                    table.c.action == "warn",
                    table.c.policy_version == POLICY_VERSION,
                    table.c.request_hash == request_digest(request),
                    table.c.token_hash
                    == hashlib.sha256(request["moderation_token"].encode()).hexdigest(),
                    table.c.expires_at > time.time(),
                    table.c.content_expires_at > time.time(),
                ),
            )
            if event:
                return event["event_id"]
    precheck(repo, request)  # Persist rejected attempts independently of enqueue rollback.
    raise AppError(
        "moderation_blocked" if decision == "block" else "moderation_confirmation_required",
        BLOCKED if decision == "block" else WARNING,
        422,
    )


def bind_admission(repo, c, job, ticket_id):
    """Create one immutable proof in the SAME serialized transaction as its job.

    Tickets can approve identical new requests within their validity window, but
    executions never share/relink proof rows. Nothing is committed if binding fails.
    """
    ticket = row(c, db.review["events"], db.review["events"].c.event_id == ticket_id)
    now = time.time()
    if not ticket or not (
        ticket["owner_id"] == job["owner_id"]
        and ticket["direction"] == "input"
        and ticket["action"] == "warn"
        and ticket["policy_version"] == POLICY_VERSION
        and ticket["request_hash"] == request_digest(job["payload"]["request"])
        and ticket["expires_at"] is not None
        and now < ticket["expires_at"]
        and now < ticket["content_expires_at"]
    ):
        raise AppError("moderation_confirmation_required", WARNING, 422)
    proof_id = add_event(
        repo,
        c,
        owner=job["owner_id"],
        direction="input",
        action="acknowledge",
        reason=ticket["reason"],
        content=None,
        job_id=job["job_id"],
        conversation_id=job["conversation_id"],
        request_hash=ticket["request_hash"],
        expires_at=ticket["expires_at"],
    )
    c.execute(
        db.review["events"]
        .update()
        .where(db.review["events"].c.event_id == proof_id)
        .values(acknowledged_at=now, content_expires_at=ticket["content_expires_at"])
    )
    payload = dict(job["payload"], moderation_event_id=proof_id)
    c.execute(db.jobs.update().where(db.jobs.c.job_id == job["job_id"]).values(payload=payload))
    job["payload"] = payload


def check_execution(repo, job):
    request = job["payload"]["request"]
    decision, reason = classify(request["question"])
    if decision == "allow":
        return
    with repo.db.write() as c:
        repo._owned(c, job["job_id"], job["lease_token"])
        proof = row(
            c,
            db.review["events"],
            db.review["events"].c.event_id == job["payload"].get("moderation_event_id"),
        )
        if (
            decision == "warn"
            and proof
            and proof["acknowledged_at"]
            and (
                proof["owner_id"] == job["owner_id"]
                and proof["job_id"] == job["job_id"]
                and proof["direction"] == "input"
                # Retain correctly bound pre-fix admissions, never unclaimed tickets.
                and proof["action"] in {"acknowledge", "warn"}
                and proof["request_hash"] == request_digest(request)
                and proof["policy_version"] == POLICY_VERSION
                and proof["expires_at"] is not None
                and proof["acknowledged_at"] <= proof["expires_at"]
                and proof["content_expires_at"] > time.time()
            )
        ):
            return
        add_event(
            repo,
            c,
            owner=job["owner_id"],
            direction="input",
            action="block",
            reason=reason,
            content=request["question"],
            job_id=job["job_id"],
        )
    raise AppError("moderation_blocked", BLOCKED, 422)


def inspect_output(repo, c, job, result, message_id):
    decision, reason = classify(result["answer"])
    visibility = "published"
    if decision == "block":
        add_event(
            repo,
            c,
            owner=job["owner_id"],
            direction="output",
            action="withhold",
            reason="policy_length_limit"
            if reason == "policy_length_limit"
            else "answer_inappropriate",
            content=(
                result["answer"]
                if len(result["answer"]) <= MAX_POLICY_CHARACTERS
                else result["answer"][:MAX_POLICY_CHARACTERS]
                + "\n[Draft truncated at policy storage limit]"
            ),
            job_id=job["job_id"],
            message_id=message_id,
        )
        result = dict(result, answer=NEUTRAL_ANSWER, citations=[], status="insufficient_evidence")
        visibility = "withheld"
    elif decision == "warn":
        event_id = add_event(
            repo,
            c,
            owner=job["owner_id"],
            direction="output",
            action="flag",
            reason=reason,
            content=None,
            job_id=job["job_id"],
            message_id=message_id,
        )
        c.execute(
            db.review["cases"]
            .insert()
            .values(
                case_id=uid(),
                owner_id=job["owner_id"],
                message_id=message_id,
                event_id=event_id,
                source="system",
                label="answer_risk_suspected",
                status="new",
                notes="",
                created_at=time.time(),
                updated_at=time.time(),
            )
        )
    return dict(result, visibility=visibility, moderation_policy_version=POLICY_VERSION)


def purge_expired(repo):
    """Erase rejected/withheld text and linkable identifiers; retain aggregate categories."""
    with repo.db.write() as c:
        table = db.review["events"]
        expired = sa.and_(
            table.c.content_expires_at <= time.time(),
            sa.or_(
                table.c.owner_id.is_not(None),
                table.c.content.is_not(None),
                table.c.job_id.is_not(None),
            ),
        )
        ids = sa.select(table.c.event_id).where(expired)
        c.execute(db.review["cases"].delete().where(db.review["cases"].c.event_id.in_(ids)))
        return c.execute(
            table.update()
            .where(expired)
            .values(
                content=None,
                owner_id=None,
                conversation_id=None,
                message_id=None,
                job_id=None,
                request_hash=None,
                token_hash=None,
                expires_at=None,
                acknowledged_at=None,
            )
        ).rowcount
