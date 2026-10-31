"""Add feedback/review without rewriting messages, jobs or the quota ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    from youtube_backend.database import review

    for table in review.values():
        table.create(op.get_bind())


def downgrade():
    from youtube_backend.database import review

    bind = op.get_bind()
    if any(bind.scalar(sa.select(sa.func.count()).select_from(t)) for t in review.values()):
        raise RuntimeError(
            "Restore a stopped paired backup; populated review data cannot be dropped"
        )
    for table in reversed(list(review.values())):
        table.drop(bind)
