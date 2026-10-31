"""Private, versioned producer-05 signals; publication never treats them as verdicts.

Adapters opt in through ExecutionContext.review_signals(). No public HTTP writer,
provider invocation, answer-schema change, new table or policy-version substitution.
"""

import hashlib
import time
from typing import Literal

import sqlalchemy as sa
from pydantic import ConfigDict, Field

from . import database as db
from .errors import AppError
from .repository import digest, uid
from .schemas import Schema

POLICY_VERSION = "chat-review-draft-v1"


class AnswerReviewSignal(Schema):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    contract_version: Literal["answer-review-signal-v1"] = "answer-review-signal-v1"
    producer: Literal["05_ai_answers_analysis"] = "05_ai_answers_analysis"
    policy_version: Literal["chat-review-draft-v1"]
    reason: Literal["insufficient_evidence", "missing_citations", "possible_instruction_override"]
    source: Literal["system_rule"] = "system_rule"
    confirmed: Literal[False] = False


class SignalBatch(Schema):
    signals: list[AnswerReviewSignal] = Field(max_length=3)


def attempt_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def stage(repo, job_id, lease_token, values):
    signals = SignalBatch(signals=values).signals
    with repo.db.write() as c:
        job = repo._owned(c, job_id, lease_token)
        if job["kind"] != "chat":
            raise AppError("unsupported_review_target", "Answer signals apply only to chat", 422)
        events = db.review["events"]
        for signal in signals:
            identity = digest(signal.model_dump())
            exists = c.scalar(
                sa.select(events.c.event_id)
                .where(
                    events.c.job_id == job_id,
                    events.c.action == "pending_sig",
                    events.c.token_hash == attempt_hash(lease_token),
                    events.c.request_hash == identity,
                )
                .limit(1)
            )
            if exists:
                continue
            now = time.time()
            c.execute(
                events.insert().values(
                    event_id=uid(),
                    owner_id=job["owner_id"],
                    job_id=job_id,
                    conversation_id=job["conversation_id"],
                    direction="output",
                    action="pending_sig",
                    reason=signal.reason,
                    policy_version=signal.policy_version,
                    token_hash=attempt_hash(lease_token),
                    request_hash=identity,
                    content=None,
                    content_expires_at=now + repo.settings.moderation_retention_days * 86400,
                    created_at=now,
                )
            )


def publish(repo, c, job, message_id):
    """Call inside finish's lease/source/guard-checked publication transaction."""
    events, cases = db.review["events"], db.review["cases"]
    pending = list(
        c.execute(
            sa.select(events).where(
                events.c.job_id == job["job_id"],
                events.c.action == "pending_sig",
                events.c.token_hash == attempt_hash(job["lease_token"]),
            )
        ).mappings()
    )
    for event in pending:
        if event["content_expires_at"] <= time.time():
            continue
        signal = AnswerReviewSignal(policy_version=event["policy_version"], reason=event["reason"])
        c.execute(
            events.update()
            .where(events.c.event_id == event["event_id"])
            .values(
                action="signal",
                message_id=message_id,
                token_hash=None,
            )
        )
        c.execute(
            cases.insert().values(
                case_id=uid(),
                owner_id=job["owner_id"],
                message_id=message_id,
                event_id=event["event_id"],
                source="system",
                label=signal.reason,
                status="new",
                notes="",
                created_at=time.time(),
                updated_at=time.time(),
            )
        )
    # Unpublished metadata from earlier attempts must never become current cases.
    c.execute(
        events.delete().where(events.c.job_id == job["job_id"], events.c.action == "pending_sig")
    )


def admin_metadata(event):
    """Only called from the capability/audit-protected administrator detail route."""
    return dict(
        **AnswerReviewSignal(
            policy_version=event["policy_version"], reason=event["reason"]
        ).model_dump(),
        publication_effect="none",
    )
