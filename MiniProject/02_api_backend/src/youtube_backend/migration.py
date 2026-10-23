from pathlib import Path

from alembic import command
from alembic.config import Config


def alembic_config(connection):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.attributes["connection"] = connection
    return config


def upgrade_database(database, revision="head", *, allow_legacy=False):
    with database.engine.begin() as connection:
        from alembic.runtime.migration import MigrationContext

        if (
            MigrationContext.configure(connection).get_current_revision() == "0001"
            and revision == "head"
            and not allow_legacy
        ):
            raise RuntimeError(
                "Stop API/workers and use yk-auth migrate with a paired backup first"
            )
        command.upgrade(alembic_config(connection), revision)
