import argparse
import asyncio
import logging
import signal
from contextlib import suppress

from .config import Settings
from .database import Database
from .migration import upgrade_database
from .repository import Repository
from .runtime import ManagedAdapters
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
        asyncio.run(run_worker(settings, database, once=args.once))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        database.close()


async def run_worker(settings, database, *, once=False):
    repository = Repository(database, settings)
    runtime = ManagedAdapters(settings, repository)
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    registered = False
    try:
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal.SIGTERM, task.cancel)
            registered = True
        await runtime.start()
        instance = Worker(repository, runtime, settings)
        await (instance.run_once() if once else instance.run_forever())
    finally:
        try:
            await runtime.close()
        finally:
            if registered:
                loop.remove_signal_handler(signal.SIGTERM)


def integration_init():
    parser = argparse.ArgumentParser(description="Explicitly initialize 02 and additive 04 schemas")
    parser.parse_args()
    from youtube_rag.manifest import initialize

    settings = Settings()
    database = Database(settings.database_url)
    try:
        upgrade_database(database)
        Repository(database, settings).check_mode()
        initialize(database)
        print("Backend schema 0001 and RAG manifest v1 initialized.")
    finally:
        database.close()


def demo_seed():
    parser = argparse.ArgumentParser(
        description="Explicit offline-only transcript seed; no YouTube fetch"
    )
    parser.add_argument("--video-id", action="append", required=True)
    args = parser.parse_args()
    settings = Settings()
    if (
        settings.adapter_mode != "custom"
        or settings.backend_integration_profile != "offline"
        or settings.adapter_factory != "youtube_backend.team:create_adapters"
    ):
        parser.error("Seeding requires the offline backend team factory and a dedicated database")
    database = Database(settings.database_url)
    try:
        asyncio.run(seed_offline(settings, database, args.video_id))
    finally:
        database.close()


async def seed_offline(settings, database, video_ids):
    from .errors import AppError
    from .fixture_adapter import FixtureAdapters
    from .urls import VIDEO_ID, canonical_url

    if (
        settings.app_env not in {"development", "test"}
        or settings.adapter_mode != "custom"
        or settings.backend_integration_profile != "offline"
        or settings.adapter_factory != "youtube_backend.team:create_adapters"
    ):
        raise AppError(
            "fixture_forbidden", "Seeding requires the dedicated offline team profile", 409
        )

    if not all(VIDEO_ID.fullmatch(video_id) for video_id in video_ids):
        raise ValueError("Provide valid 11-character video IDs")
    repository = Repository(database, settings)
    runtime = ManagedAdapters(settings, repository)

    class SeedOnly:
        ingest = FixtureAdapters(repository, settings).ingest

        def __getattr__(self, name):
            return getattr(runtime, name)

    try:
        await runtime.start()
        instance = Worker(repository, SeedOnly(), settings)
        for item in repository.import_urls([canonical_url(v) for v in video_ids]):
            job = repository.get_job(item["job_id"])
            if job["stage"] != "ready":
                await instance.run_once(item["job_id"])
            final = repository.get_job(item["job_id"])
            if final["stage"] != "ready":
                raise RuntimeError(f"Offline seed failed: {final['error_code']}")
        print("OFFLINE ONLY: labelled transcripts and fixture embeddings seeded into real Chroma.")
    finally:
        await runtime.close()
