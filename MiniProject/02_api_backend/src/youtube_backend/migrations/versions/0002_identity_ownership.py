"""Google identity, server sessions and quarantined ownership of legacy data."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    from youtube_backend.database import (
        admin_audit,
        legacy_sources,
        login_challenges,
        sessions,
        user_videos,
        users,
    )

    bind = op.get_bind()
    for table in (users, sessions, login_challenges, admin_audit, user_videos, legacy_sources):
        table.create(bind)
    bind.exec_driver_sql("INSERT INTO legacy_sources(video_id) SELECT video_id FROM videos")
    for table in ("jobs", "conversations", "learning_artifacts"):
        # Nullable owners quarantine all existing records. Never assign first-login ownership.
        bind.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN owner_id VARCHAR(36) REFERENCES users(user_id)"
        )
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
    bind.exec_driver_sql(
        "UPDATE jobs SET state='cancelled', stage='cancelled', cancel_requested=1, "
        "error_code='legacy_owner_required', lease_token=NULL, lease_until=NULL "
        "WHERE owner_id IS NULL AND state IN ('queued','running')"
    )


def downgrade():
    # Losing account/session/ownership information is not an automatic rollback operation.
    # Empty-schema downgrade supports migration verification; populated data requires restore.
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT count(*) FROM users").scalar():
        raise RuntimeError("Restore the stopped pre-migration SQLite/Chroma backup to roll back")
    for table in ("jobs", "conversations", "learning_artifacts"):
        op.drop_index(f"ix_{table}_owner_id", table_name=table)
        bind.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN owner_id")
    for table in (
        "legacy_sources",
        "user_videos",
        "admin_audit",
        "login_challenges",
        "sessions",
        "users",
    ):
        op.drop_table(table)
