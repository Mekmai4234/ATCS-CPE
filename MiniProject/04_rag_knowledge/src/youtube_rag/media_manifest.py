"""Separate additive v3 namespace. Transcript-v1/v2 indexes are never reinterpreted."""

import sqlalchemy as sa

media_metadata = sa.MetaData()
media_runs = sa.Table(
    "rag04_media_runs_v3",
    media_metadata,
    sa.Column("run_id", sa.String, primary_key=True),
    sa.Column("video_id", sa.String, nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("snapshot", sa.JSON, nullable=False),
    sa.Column("config", sa.String, nullable=False),
    sa.Column("collection", sa.String, nullable=False),
    sa.Column("state", sa.String, nullable=False),
    sa.Column("count", sa.Integer, nullable=False),
)
media_active = sa.Table(
    "rag04_media_active_v3",
    media_metadata,
    sa.Column("video_id", sa.String, primary_key=True),
    sa.Column("generation", sa.Integer, primary_key=True),
    sa.Column("kind", sa.String, primary_key=True),
    sa.Column("run_id", sa.String, nullable=False),
)
media_chunks = sa.Table(
    "rag04_media_chunks_v3",
    media_metadata,
    sa.Column("run_id", sa.String, primary_key=True),
    sa.Column("evidence_id", sa.String, primary_key=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("data", sa.JSON, nullable=False),
)
