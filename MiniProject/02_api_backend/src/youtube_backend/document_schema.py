"""Additive immutable document versions and an atomic active pointer."""

import sqlalchemy as sa


def create_tables(metadata):
    versions = sa.Table(
        "document_versions",
        metadata,
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(200), nullable=False),
        sa.Column("video_id", sa.String(11), nullable=False, index=True),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("transcript_version", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )
    active = sa.Table(
        "document_active",
        metadata,
        sa.Column("video_id", sa.String(11), primary_key=True),
        sa.Column("version", sa.ForeignKey(versions.c.version), nullable=False),
    )
    passages = sa.Table(
        "document_passages",
        metadata,
        sa.Column("version", sa.ForeignKey(versions.c.version), primary_key=True),
        sa.Column("segment_id", sa.String(200), primary_key=True),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("normalized", sa.Text, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )
    grams = sa.Table(
        "document_grams",
        metadata,
        sa.Column("gram", sa.String(12), primary_key=True),
        sa.Column("version", sa.ForeignKey(versions.c.version), primary_key=True),
        sa.Column("segment_id", sa.String(200), primary_key=True),
    )
    return dict(versions=versions, active=active, passages=passages, grams=grams)
