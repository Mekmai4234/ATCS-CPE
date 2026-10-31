"""Additive, separately authorized feedback and review storage (revision 0004)."""

import sqlalchemy as sa


def create_tables(metadata):
    feedback = sa.Table(
        "message_feedback",
        metadata,
        sa.Column("owner_id", sa.ForeignKey("users.user_id"), primary_key=True),
        sa.Column(
            "message_id", sa.ForeignKey("messages.message_id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(40)),
        sa.Column("comment", sa.String(500), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
        sa.CheckConstraint("rating IN ('like','dislike')", name="ck_feedback_rating"),
        sa.Index("ix_feedback_updated", "updated_at", "message_id"),
    )
    events = sa.Table(
        "moderation_events",
        metadata,
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.ForeignKey("users.user_id")),
        sa.Column(
            "conversation_id", sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE")
        ),
        sa.Column("message_id", sa.ForeignKey("messages.message_id", ondelete="CASCADE")),
        sa.Column("job_id", sa.ForeignKey("jobs.job_id", ondelete="CASCADE")),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("token_hash", sa.String(64)),
        sa.Column("expires_at", sa.Float),
        sa.Column("acknowledged_at", sa.Float),
        sa.Column("content", sa.Text),
        sa.Column("content_expires_at", sa.Float, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Index("ix_moderation_expiry", "content_expires_at"),
        sa.Index("ix_moderation_job", "job_id"),
    )
    cases = sa.Table(
        "chat_review_cases",
        metadata,
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.ForeignKey("users.user_id")),
        sa.Column("message_id", sa.ForeignKey("messages.message_id", ondelete="CASCADE")),
        sa.Column("event_id", sa.ForeignKey("moderation_events.event_id", ondelete="CASCADE")),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("outcome", sa.String(20)),
        sa.Column("notes", sa.String(1000), nullable=False),
        sa.Column("reviewer_id", sa.ForeignKey("users.user_id")),
        sa.Column("reviewed_at", sa.Float),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
        sa.UniqueConstraint("message_id", "source", "label", name="uq_review_message_label"),
        sa.Index("ix_review_queue", "status", "created_at", "case_id"),
    )
    return dict(feedback=feedback, events=events, cases=cases)
