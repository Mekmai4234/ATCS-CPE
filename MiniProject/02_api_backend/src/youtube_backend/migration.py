from pathlib import Path

from alembic import command
from alembic.config import Config


def alembic_config(connection):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.attributes["connection"] = connection
    return config


def upgrade_database(database, revision="head"):
    with database.engine.begin() as connection:
        command.upgrade(alembic_config(connection), revision)
