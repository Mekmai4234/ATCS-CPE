"""Message feedback and explicitly enabled, audited administrator content access."""

import time
from typing import Literal

import sqlalchemy as sa
from pydantic import Field, model_validator

from . import database as db
from .admin import require_admin
from .errors import AppError
from .repository import ACTIVE, row, uid
from .schemas import Schema


class Feedback(Schema):
    rating: Literal["like", "dislike"]
    reason: (
        Literal[
            "off_topic",
            "incorrect",
            "citation_mismatch",
            "insufficient_evidence",
            "inappropriate",
            "other",
        ]
        | None
    ) = None
    comment: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def dislike_details(self):
        if self.rating == "like" and (self.reason or self.comment):
            raise ValueError("Reasons and comments belong to dislike feedback")
        return self


class ReviewUpdate(Schema):
    status: Literal["in_review", "reviewed"]
    outcome: Literal["confirmed", "false_positive", "inconclusive"] | None = None
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def reviewed_outcome(self):
        if (self.status == "reviewed") != (self.outcome is not None):
            raise ValueError("Only reviewed cases require an outcome")
        return self


def require_review(repo, c):
    admin = require_admin(c)
    if not repo.settings.chat_review_enabled:
        raise AppError(
            "chat_review_disabled", "Deploy the review notice before enabling access", 403
        )
    if admin["user_id"] not in repo.settings.chat_review_admin_ids:
        raise AppError("chat_review_capability_required", "Content review capability required", 403)
    return admin


def audit(c, admin, owner, action, **data):
    c.execute(
        db.admin_audit.insert().values(
            actor_id=admin["user_id"],
            target_id=owner,
            action=action,
            data=data,
            created_at=time.time(),
        )
    )


def owned_message(repo, c, message_id):
    message = row(c, db.messages, db.messages.c.message_id == message_id)
    if not message:
        raise AppError("not_found", "Message not found", 404)
    conversation = row(
        c, db.conversations, db.conversations.c.conversation_id == message["conversation_id"]
    )
    repo._private(c, conversation)
    owner = repo._actor(c)
    if not owner:
        raise AppError("authentication_required", "Feedback requires a member account", 401)
    job = row(c, db.jobs, db.jobs.c.job_id == message["job_id"])
    if (
        message["role"] != "assistant"
        or job["state"] != "completed"
        or ((job["result"] or {}).get("visibility") == "withheld")
    ):
        raise AppError("feedback_unavailable", "Only published assistant answers can be rated", 409)
    return owner


def feedback_for(c, owner, message_id):
    table = db.review["feedback"]
    value = row(c, table, sa.and_(table.c.owner_id == owner, table.c.message_id == message_id))
    if value:
        return {k: value[k] for k in ("rating", "reason", "comment", "revision", "updated_at")}
    return None


def set_feedback(repo, message_id, body=None):
    with repo.db.write() as c:
        owner = owned_message(repo, c, message_id)
        table, cases = db.review["feedback"], db.review["cases"]
        where = sa.and_(table.c.owner_id == owner, table.c.message_id == message_id)
        previous = row(c, table, where)
        if body is None:
            c.execute(table.delete().where(where))
        else:
            data = body.model_dump()
            if previous and all(previous[k] == data[k] for k in data):
                return dict(message_id=message_id, feedback=feedback_for(c, owner, message_id))
            now = time.time()
            values = dict(
                data, revision=previous["revision"] + 1 if previous else 1, updated_at=now
            )
            if previous:
                c.execute(table.update().where(where).values(**values))
            else:
                c.execute(
                    table.insert().values(
                        **values, owner_id=owner, message_id=message_id, created_at=now
                    )
                )
        user_case = sa.and_(cases.c.message_id == message_id, cases.c.source == "user")
        if body and body.rating == "dislike":
            current = row(c, cases, user_case)
            values = dict(
                status="new",
                outcome=None,
                reviewer_id=None,
                reviewed_at=None,
                notes="",
                updated_at=time.time(),
            )
            if current:
                c.execute(cases.update().where(user_case).values(**values))
            else:
                c.execute(
                    cases.insert().values(
                        **values,
                        case_id=uid(),
                        owner_id=owner,
                        message_id=message_id,
                        source="user",
                        label="user_dissatisfied",
                        created_at=time.time(),
                    )
                )
        else:
            c.execute(cases.delete().where(user_case))
        return dict(message_id=message_id, feedback=feedback_for(c, owner, message_id))


def review_list(
    repo, *, limit, offset, status="pending", rating=None, label=None, q="", after=None, before=None
):
    cases, feedback = db.review["cases"], db.review["feedback"]
    with repo.db.write() as c:
        admin = require_review(repo, c)
        conditions = []
        if status == "pending":
            conditions.append(cases.c.status.in_(["new", "in_review"]))
        elif status != "all":
            conditions.append(cases.c.status == status)
        if label:
            conditions.append(cases.c.label == label)
        if after is not None:
            conditions.append(cases.c.created_at >= after)
        if before is not None:
            conditions.append(cases.c.created_at <= before)
        if rating:
            conditions.append(
                sa.exists(
                    sa.select(feedback.c.message_id).where(
                        feedback.c.message_id == cases.c.message_id, feedback.c.rating == rating
                    )
                )
            )
        if q:
            answer = db.messages.alias("answer")
            question = db.messages.alias("question")
            event = db.review["events"]
            # SQL EXISTS, escaped wildcard input, bounded page; no Python scan of chats.
            conditions.append(
                sa.or_(
                    sa.exists(
                        sa.select(question.c.message_id)
                        .join(answer, answer.c.job_id == question.c.job_id)
                        .where(
                            answer.c.message_id == cases.c.message_id,
                            question.c.role == "user",
                            question.c.content.contains(q, autoescape=True),
                        )
                    ),
                    sa.exists(
                        sa.select(event.c.event_id).where(
                            event.c.event_id == cases.c.event_id,
                            event.c.direction == "input",
                            event.c.content_expires_at > time.time(),
                            event.c.content.contains(q, autoescape=True),
                        )
                    ),
                )
            )
        statement = sa.select(cases).where(*conditions)
        total = c.scalar(sa.select(sa.func.count()).select_from(statement.subquery()))
        items = []
        for case in c.execute(
            statement.order_by(cases.c.created_at.desc(), cases.c.case_id)
            .limit(limit)
            .offset(offset)
        ).mappings():
            # Only a short question excerpt, audited on every returned row.
            items.append(
                {
                    k: case[k]
                    for k in (
                        "case_id",
                        "message_id",
                        "source",
                        "label",
                        "status",
                        "outcome",
                        "created_at",
                    )
                }
            )
            if case["message_id"]:
                detail, owner = message_detail(c, case["message_id"])
                items[-1]["question_excerpt"] = (detail["question"] or {}).get("content", "")[:120]
                items[-1]["member_ref"] = (owner or "")[:8]
                audit(c, admin, owner, "chat_review_list", case_id=case["case_id"])
            elif case["event_id"]:
                event = row(
                    c, db.review["events"], db.review["events"].c.event_id == case["event_id"]
                )
                items[-1]["question_excerpt"] = (
                    (event["content"] or "")[:120]
                    if (
                        event
                        and event["direction"] == "input"
                        and event["content_expires_at"] > time.time()
                    )
                    else ""
                )
                items[-1]["member_ref"] = (case["owner_id"] or "")[:8]
                audit(c, admin, case["owner_id"], "chat_review_list", case_id=case["case_id"])
        counts = dict(
            c.execute(
                sa.select(feedback.c.rating, sa.func.count()).group_by(feedback.c.rating)
            ).all()
        )
        return dict(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            stats=dict(
                like=counts.get("like", 0),
                dislike=counts.get("dislike", 0),
                pending=c.scalar(
                    sa.select(sa.func.count())
                    .select_from(cases)
                    .where(cases.c.status.in_(["new", "in_review"]))
                ),
                withheld=c.scalar(
                    sa.select(sa.func.count())
                    .select_from(db.review["events"])
                    .where(db.review["events"].c.action == "withhold")
                ),
            ),
        )


def message_detail(c, message_id):
    message = row(c, db.messages, db.messages.c.message_id == message_id)
    if not message or message["role"] != "assistant":
        raise AppError("not_found", "Assistant message not found", 404)
    job = row(c, db.jobs, db.jobs.c.job_id == message["job_id"])
    question = row(
        c,
        db.messages,
        sa.and_(db.messages.c.job_id == message["job_id"], db.messages.c.role == "user"),
    )
    citations = list(
        c.execute(
            sa.select(db.citations.c.data).where(db.citations.c.message_id == message_id)
        ).scalars()
    )
    return dict(
        message_id=message_id,
        job_id=message["job_id"],
        conversation_id=message["conversation_id"],
        question=question,
        answer=message,
        visibility=(job["result"] or {}).get("visibility", "published"),
        scope=message["scope"],
        citations=citations,
        provider_metadata=(job["result"] or {}).get("provider_metadata"),
        feedback=feedback_for(c, job["owner_id"], message_id),
    ), job["owner_id"]


def detail(repo, case_id=None, message_id=None):
    with repo.db.write() as c:
        admin = require_review(repo, c)
        case = (
            row(c, db.review["cases"], db.review["cases"].c.case_id == case_id) if case_id else None
        )
        if case_id and not case:
            raise AppError("not_found", "Review case not found", 404)
        mid = case["message_id"] if case else message_id
        data, owner = message_detail(c, mid) if mid else ({}, case["owner_id"])
        data["case"] = case
        event = (
            row(c, db.review["events"], db.review["events"].c.event_id == case["event_id"])
            if case and case["event_id"]
            else None
        )
        if event:
            # Even if the scheduled purge is late, expired drafts are never returned.
            data["moderation"] = dict(
                direction=event["direction"],
                action=event["action"],
                reason=event["reason"],
                policy_version=event["policy_version"],
                draft=event["content"] if event["content_expires_at"] > time.time() else None,
                visible_to_user=False if event["action"] in {"block", "withhold"} else True,
            )
        audit(c, admin, owner, "chat_review_open", case_id=case_id, message_id=mid)
        return data


def update_case(repo, case_id, body):
    with repo.db.write() as c:
        admin = require_review(repo, c)
        table = db.review["cases"]
        case = row(c, table, table.c.case_id == case_id)
        if not case:
            raise AppError("not_found", "Review case not found", 404)
        if case["status"] == "new" and body.status == "reviewed":
            raise AppError(
                "invalid_review_transition", "Start review before recording an outcome", 409
            )
        now = time.time()
        c.execute(
            table.update()
            .where(table.c.case_id == case_id)
            .values(
                **body.model_dump(), reviewer_id=admin["user_id"], reviewed_at=now, updated_at=now
            )
        )
        audit(
            c,
            admin,
            case["owner_id"],
            "chat_review_update",
            case_id=case_id,
            status=body.status,
            outcome=body.outcome,
        )
        return dict(case_id=case_id, **body.model_dump(), reviewed_at=now)


def normal_messages(repo, limit, offset):
    with repo.db.read() as c:
        require_review(repo, c)
        condition = db.messages.c.role == "assistant"
        ids = list(
            c.execute(
                sa.select(db.messages.c.message_id)
                .where(condition)
                .order_by(db.messages.c.created_at.desc(), db.messages.c.message_id)
                .limit(limit)
                .offset(offset)
            ).scalars()
        )
        return dict(
            items=[dict(message_id=mid) for mid in ids],
            limit=limit,
            offset=offset,
            total=c.scalar(sa.select(sa.func.count()).select_from(db.messages).where(condition)),
        )


def delete_conversation(repo, conversation_id):
    """Erase chat content and review copies, preserve durable quota accounting/job identity."""
    with repo.db.write() as c:
        conversation = row(
            c, db.conversations, db.conversations.c.conversation_id == conversation_id
        )
        if not conversation:
            raise AppError("not_found", "Conversation not found", 404)
        repo._private(c, conversation)
        jobs = list(
            c.execute(
                sa.select(db.jobs).where(db.jobs.c.conversation_id == conversation_id)
            ).mappings()
        )
        if any(job["state"] in ACTIVE for job in jobs):
            raise AppError("conversation_busy", "Cancel active jobs before deleting history", 409)
        mids = sa.select(db.messages.c.message_id).where(
            db.messages.c.conversation_id == conversation_id
        )
        c.execute(
            db.review["events"]
            .delete()
            .where(db.review["events"].c.conversation_id == conversation_id)
        )
        c.execute(db.citations.delete().where(db.citations.c.message_id.in_(mids)))
        # New review rows cascade with their original message/job. Blocked input
        # attached to a running job is erased too; quota reservations stay intact.
        for job in jobs:
            events = db.review["events"]
            c.execute(events.delete().where(events.c.job_id == job["job_id"]))
            payload = dict(job["payload"], request={}, history=[])
            c.execute(db.events.delete().where(db.events.c.job_id == job["job_id"]))
            c.execute(
                db.jobs.update()
                .where(db.jobs.c.job_id == job["job_id"])
                .values(
                    payload=payload,
                    result=None,
                    conversation_id=None,
                    retryable=False,
                    state="cancelled",
                    stage="cancelled",
                    error_code="history_deleted",
                )
            )
        c.execute(db.messages.delete().where(db.messages.c.conversation_id == conversation_id))
        c.execute(
            db.conversations.delete().where(db.conversations.c.conversation_id == conversation_id)
        )
    return dict(deleted=True)
