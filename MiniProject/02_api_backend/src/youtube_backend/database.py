from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import make_url

metadata = sa.MetaData()
SCHEMA_REVISION = "0002"

users = sa.Table(
    "users",
    metadata,
    sa.Column("user_id", sa.String(36), primary_key=True),
    sa.Column("google_sub", sa.String(255), nullable=False, unique=True),
    sa.Column("email", sa.String(320)),
    sa.Column("name", sa.String(200)),
    sa.Column("picture", sa.Text),
    sa.Column("role", sa.String(10), nullable=False),
    sa.Column("status", sa.String(12), nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("updated_at", sa.Float, nullable=False),
    sa.CheckConstraint("role IN ('user','admin')", name="ck_user_role"),
    sa.CheckConstraint("status IN ('active','suspended')", name="ck_user_status"),
)
sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("user_id", sa.ForeignKey("users.user_id"), nullable=False, index=True),
    sa.Column("csrf_hash", sa.String(64), nullable=False),
    sa.Column("expires_at", sa.Float, nullable=False),
    sa.Column("revoked", sa.Boolean, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
)
login_challenges = sa.Table(
    "login_challenges",
    metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("csrf_hash", sa.String(64), nullable=False),
    sa.Column("nonce_hash", sa.String(64), nullable=False),
    sa.Column("ip_hash", sa.String(64), nullable=False, index=True),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("expires_at", sa.Float, nullable=False),
    sa.Column("consumed", sa.Boolean, nullable=False),
)
admin_audit = sa.Table(
    "admin_audit",
    metadata,
    sa.Column("audit_id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("actor_id", sa.ForeignKey("users.user_id")),
    sa.Column("target_id", sa.ForeignKey("users.user_id"), nullable=False),
    sa.Column("action", sa.String(40), nullable=False),
    sa.Column("data", sa.JSON, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
)

videos = sa.Table(
    "videos",
    metadata,
    sa.Column("video_id", sa.String(11), primary_key=True),
    sa.Column("canonical_url", sa.Text, nullable=False),
    sa.Column("title", sa.Text),
    sa.Column("channel_id", sa.String(200)),
    sa.Column("channel_title", sa.Text),
    sa.Column("thumbnail_url", sa.Text),
    sa.Column("published_at", sa.String(10)),
    sa.Column("status", sa.String(30), nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("transcript_version", sa.String(64)),
    sa.Column("indexed_version", sa.String(64)),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("updated_at", sa.Float, nullable=False),
)

transcripts = sa.Table(
    "transcripts",
    metadata,
    sa.Column("video_id", sa.ForeignKey("videos.video_id"), primary_key=True),
    sa.Column("version", sa.String(64), primary_key=True),
    sa.Column("language", sa.String(30), nullable=False),
    sa.Column("source", sa.String(100), nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
)

segments = sa.Table(
    "transcript_segments",
    metadata,
    sa.Column("video_id", sa.String(11), primary_key=True),
    sa.Column("version", sa.String(64), primary_key=True),
    sa.Column("segment_id", sa.String(200), primary_key=True),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("start_seconds", sa.Float, nullable=False),
    sa.Column("duration_seconds", sa.Float, nullable=False),
    sa.ForeignKeyConstraint(
        ["video_id", "version"], ["transcripts.video_id", "transcripts.version"]
    ),
)

conversations = sa.Table(
    "conversations",
    metadata,
    sa.Column("conversation_id", sa.String(36), primary_key=True),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("owner_id", sa.ForeignKey("users.user_id"), index=True),
)

jobs = sa.Table(
    "jobs",
    metadata,
    sa.Column("job_id", sa.String(36), primary_key=True),
    sa.Column("owner_id", sa.ForeignKey("users.user_id"), index=True),
    sa.Column("request_id", sa.String(36), nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("video_id", sa.ForeignKey("videos.video_id")),
    sa.Column("generation", sa.Integer),
    sa.Column("conversation_id", sa.ForeignKey("conversations.conversation_id")),
    sa.Column("idempotency_key", sa.String(220), unique=True),
    sa.Column("request_hash", sa.String(64)),
    sa.Column("state", sa.String(30), nullable=False),
    sa.Column("stage", sa.String(40), nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("result", sa.JSON),
    sa.Column("error_code", sa.String(100)),
    sa.Column("retryable", sa.Boolean, nullable=False),
    sa.Column("attempt_count", sa.Integer, nullable=False),
    sa.Column("max_attempts", sa.Integer, nullable=False),
    sa.Column("available_at", sa.Float, nullable=False),
    sa.Column("lease_token", sa.String(36)),
    sa.Column("lease_until", sa.Float),
    sa.Column("cancel_requested", sa.Boolean, nullable=False),
    sa.Column("deadline_at", sa.Float),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("updated_at", sa.Float, nullable=False),
    sa.Index("ix_jobs_claim", "state", "available_at", "created_at"),
)

messages = sa.Table(
    "messages",
    metadata,
    sa.Column("message_id", sa.String(36), primary_key=True),
    sa.Column("conversation_id", sa.ForeignKey("conversations.conversation_id"), nullable=False),
    sa.Column("job_id", sa.ForeignKey("jobs.job_id"), nullable=False),
    sa.Column("role", sa.String(20), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("scope", sa.JSON, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.UniqueConstraint("job_id", "role", name="uq_message_job_role"),
)

citations = sa.Table(
    "citations",
    metadata,
    sa.Column("message_id", sa.ForeignKey("messages.message_id"), primary_key=True),
    sa.Column("citation_id", sa.String(200), primary_key=True),
    sa.Column("video_id", sa.String(11), nullable=False),
    sa.Column("data", sa.JSON, nullable=False),
)

events = sa.Table(
    "research_events",
    metadata,
    sa.Column("event_id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.ForeignKey("jobs.job_id"), nullable=False),
    sa.Column("data", sa.JSON, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
)

artifacts = sa.Table(
    "learning_artifacts",
    metadata,
    sa.Column("artifact_id", sa.String(36), primary_key=True),
    sa.Column("owner_id", sa.ForeignKey("users.user_id"), index=True),
    sa.Column("job_id", sa.ForeignKey("jobs.job_id"), nullable=False),
    sa.Column("scope", sa.JSON, nullable=False),
    sa.Column("data", sa.JSON, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
)

# ONLY fixture mode uses this table. Production vectors belong to module 04.
user_videos = sa.Table(
    "user_videos",
    metadata,
    sa.Column("user_id", sa.ForeignKey("users.user_id"), primary_key=True),
    sa.Column("video_id", sa.ForeignKey("videos.video_id"), primary_key=True),
    sa.Column("created_at", sa.Float, nullable=False),
)

legacy_sources = sa.Table(
    "legacy_sources",
    metadata,
    sa.Column("video_id", sa.ForeignKey("videos.video_id"), primary_key=True),
)

fixture_chunks = sa.Table(
    "fixture_chunks",
    metadata,
    sa.Column("video_id", sa.String(11), primary_key=True),
    sa.Column("generation", sa.Integer, primary_key=True),
    sa.Column("chunk_id", sa.String(200), primary_key=True),
    sa.Column("data", sa.JSON, nullable=False),
)


class Database:
    def __init__(self, url: str):
        Path(make_url(url).database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = sa.create_engine(
            url, connect_args={"check_same_thread": False, "timeout": 15}
        )

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=15000")
            connection.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def read(self):
        with self.engine.connect() as connection:
            yield connection

    @contextmanager
    def write(self):
        # Acquire the SQLite write lock before read-modify-write decisions.
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def check_schema(self):
        with self.read() as connection:
            from alembic.runtime.migration import MigrationContext

            if MigrationContext.configure(connection).get_current_revision() != SCHEMA_REVISION:
                raise RuntimeError("Database schema missing/outdated; run yk-db upgrade head")

    def close(self):
        self.engine.dispose()
