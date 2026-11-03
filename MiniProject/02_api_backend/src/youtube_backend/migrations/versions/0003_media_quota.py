"""Add media evidence and durable shared Gemini budgets; preserve v1 data."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    from youtube_backend.database import v2

    for table in v2.values():
        table.create(op.get_bind())


def downgrade():
    from youtube_backend.database import v2

    bind = op.get_bind()
    if any(bind.scalar(sa.select(sa.func.count()).select_from(t)) for t in v2.values()):
        raise RuntimeError(
            "Restore the paired backup; populated media/quota data cannot be dropped"
        )
    for table in reversed(list(v2.values())):
        table.drop(bind)
