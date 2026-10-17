from alembic import context

from youtube_backend.database import metadata


def run_migrations():
    connection = context.config.attributes["connection"]
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
