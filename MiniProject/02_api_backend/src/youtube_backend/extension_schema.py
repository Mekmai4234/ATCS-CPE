"""Additive media/quota tables. No changes to transcript-v1 columns or rows."""

import sqlalchemy as sa


def create_tables(metadata):
    def table(name, *columns):
        return sa.Table(name, metadata, *columns)

    def col(name, kind, **kwargs):
        return sa.Column(name, kind, **kwargs)

    def video_columns():
        return [
            col("video_id", sa.ForeignKey("videos.video_id"), nullable=False, index=True),
            col("generation", sa.Integer, nullable=False),
        ]

    assets = table(
        "media_assets",
        col("asset_id", sa.String, primary_key=True),
        *video_columns(),
        col("sha256", sa.String, nullable=False),
        col("mime", sa.String, nullable=False),
        col("size", sa.Integer, nullable=False),
        col("path", sa.String, nullable=False),
        col("created_at", sa.Float, nullable=False),
    )
    frames = table(
        "media_frames",
        col("frame_id", sa.String, primary_key=True),
        col("asset_id", sa.ForeignKey("media_assets.asset_id"), nullable=False),
        *video_columns(),
        col("timestamp_seconds", sa.Float, nullable=False),
        col("sampling_version", sa.String, nullable=False),
    )
    revisions = table(
        "evidence_revisions",
        col("revision_id", sa.String, primary_key=True),
        *video_columns(),
        col("kind", sa.String, nullable=False),
        col("version", sa.String, nullable=False),
        col("data", sa.JSON, nullable=False),
        col("created_at", sa.Float, nullable=False),
        sa.UniqueConstraint("video_id", "generation", "kind", "version"),
    )
    states = table(
        "media_states",
        col("video_id", sa.ForeignKey("videos.video_id"), primary_key=True),
        col("generation", sa.Integer, primary_key=True),
        col("state", sa.String, nullable=False),
        col("error_code", sa.String),
        col("data", sa.JSON),
        col("updated_at", sa.Float, nullable=False),
    )
    cache = table(
        "analysis_cache",
        col("cache_id", sa.String, primary_key=True),
        col("owner_id", sa.ForeignKey("users.user_id"), nullable=False),
        *video_columns(),
        col("evidence_version", sa.String, nullable=False),
        col("prompt_version", sa.String, nullable=False),
        col("model", sa.String, nullable=False),
        col("input_hash", sa.String, nullable=False),
        col("data", sa.JSON, nullable=False),
        col("expires_at", sa.Float, nullable=False),
    )
    reservations = table(
        "gemini_reservations",
        col("reservation_id", sa.String, primary_key=True),
        col("project", sa.String, nullable=False),
        col("policy_digest", sa.String, nullable=False),
        col("bucket", sa.String, nullable=False),
        col("model", sa.String, nullable=False),
        col("endpoint", sa.String, nullable=False),
        col("role", sa.String, nullable=False),
        col("owner_id", sa.String, nullable=False),
        col("job_id", sa.ForeignKey("jobs.job_id"), nullable=False),
        col("lease_token", sa.String, nullable=False),
        col("call_key", sa.String, nullable=False),
        col("input_hash", sa.String),
        col("state", sa.String, nullable=False),
        col("tokens", sa.Integer, nullable=False),
        col("created_at", sa.Float, nullable=False, index=True),
        col("expires_at", sa.Float, nullable=False),
        col("returned_model", sa.String),
        col("returned_allowlist", sa.JSON, nullable=False),
        sa.UniqueConstraint("project", "job_id", "lease_token", "call_key"),
    )
    waits = table(
        "gemini_waiters",
        col("wait_id", sa.String, primary_key=True),
        col("project", sa.String, nullable=False),
        col("owner_id", sa.String, nullable=False),
        col("job_id", sa.ForeignKey("jobs.job_id"), nullable=False),
        col("priority", sa.Integer, nullable=False),
        col("created_at", sa.Float, nullable=False),
        col("expires_at", sa.Float, nullable=False),
    )
    circuits = table(
        "gemini_circuits",
        col("key", sa.String, primary_key=True),
        col("failures", sa.Integer, nullable=False),
        col("blocked_until", sa.Float, nullable=False),
        col("reason", sa.String, nullable=False),
        col("time_source", sa.String, nullable=False),
    )
    pauses = table(
        "job_waits",
        col("job_id", sa.ForeignKey("jobs.job_id"), primary_key=True),
        col("data", sa.JSON, nullable=False),
    )
    policies = table(
        "gemini_policy",
        col("project", sa.String, primary_key=True),
        col("digest", sa.String, nullable=False),
    )
    return dict(
        assets=assets,
        frames=frames,
        revisions=revisions,
        media_states=states,
        cache=cache,
        reservations=reservations,
        waiters=waits,
        circuits=circuits,
        pauses=pauses,
        policies=policies,
    )
