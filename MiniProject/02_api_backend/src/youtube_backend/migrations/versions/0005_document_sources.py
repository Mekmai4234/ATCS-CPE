"""Immutable user-supplied documents; never rewrite caption/chat/ledger data."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    from youtube_backend.database import documents

    for table in documents.values():
        table.create(op.get_bind())


def downgrade():
    from youtube_backend.database import documents

    bind = op.get_bind()
    if any(bind.scalar(sa.select(sa.func.count()).select_from(t)) for t in documents.values()):
        raise RuntimeError("Restore paired backup; populated document versions cannot be dropped")
    for table in reversed(list(documents.values())):
        table.drop(bind)
