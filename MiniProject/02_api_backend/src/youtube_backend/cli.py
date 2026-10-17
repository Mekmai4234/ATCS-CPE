import argparse
import asyncio
import logging

from .config import Settings
from .database import Database
from .integrations import load_adapters
from .migration import upgrade_database
from .repository import Repository
from .worker import Worker


def configure_logging(settings):
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")


def migrate():
    parser = argparse.ArgumentParser(description="Apply the module 02 database migrations")
    parser.add_argument("command", choices=["upgrade"])
    parser.add_argument("revision", nargs="?", default="head", choices=["head"])
    parser.parse_args()
    database = Database(Settings().database_url)
    try:
        upgrade_database(database)
        print("Database upgraded to head (0001).")
    finally:
        database.close()


def api():
    import uvicorn

    settings = Settings()
    configure_logging(settings)
    uvicorn.run(
        "youtube_backend.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
    )


def worker():
    parser = argparse.ArgumentParser(description="Run the durable module 02 worker")
    parser.add_argument("--once", action="store_true", help="Process at most one ready job")
    args = parser.parse_args()
    settings = Settings()
    configure_logging(settings)
    database = Database(settings.database_url)
    try:
        database.check_schema()
        repository = Repository(database, settings)
        repository.check_mode()
        instance = Worker(repository, load_adapters(settings, repository), settings)
        asyncio.run(instance.run_once() if args.once else instance.run_forever())
    except KeyboardInterrupt:
        pass
    finally:
        database.close()
