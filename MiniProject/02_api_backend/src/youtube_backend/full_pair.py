"""Explicit binding for fresh full-system SQLite/Chroma pairs; no legacy adoption."""

import json
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from . import database as tables
from .database import Database
from .migration import upgrade_database
from .repository import Repository

metadata = sa.MetaData()
binding = sa.Table(
    "backend02_full_pair",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("data", sa.JSON, nullable=False),
)
MARKER = ".backend02-pair.json"


def identity(settings):
    return {
        "version": 1,
        "profile": settings.backend_integration_profile,
        "factory": settings.adapter_factory,
        "fingerprint": settings.services()["rag"].fingerprint,
    }


def check_pair(settings):
    path = Path(make_url(settings.database_url).database)
    if not path.is_file():
        raise ValueError("Initialize a new full-system pair first")
    database = Database(settings.database_url)
    try:
        database.check_schema()
        Repository(database, settings).check_mode()
        from youtube_rag.manifest import Manifest

        Manifest(database)
        with database.read() as connection:
            record = connection.scalar(sa.select(binding.c.data).where(binding.c.id == 1))
        marker = json.loads((Path(settings.chroma_persist_dir) / MARKER).read_text("utf-8"))
        if not record or marker != record or not record.get("pair_id"):
            raise ValueError("SQLite/Chroma pair does not match")
        if {key: record.get(key) for key in identity(settings)} != identity(settings):
            raise ValueError("Profile or embedding configuration changed; use a new pair")
        return record
    finally:
        database.close()


def initialize_pair(settings):
    from youtube_rag.manifest import initialize, runs

    expected = identity(settings)
    chroma = Path(settings.chroma_persist_dir)
    path = Path(make_url(settings.database_url).database)
    if path.is_file():
        # An existing binding is immutable. Repeated initialization only verifies it.
        database = Database(settings.database_url)
        try:
            if sa.inspect(database.engine).has_table(binding.name):
                return check_pair(settings)
        finally:
            database.close()
        # Do not migrate or adopt any existing unbound database.
        raise ValueError("Existing unbound SQLite file; select a fresh pair")
    if chroma.exists() and any(chroma.iterdir()):
        raise ValueError("Existing unbound Chroma directory; select a fresh pair")
    database = Database(settings.database_url)
    try:
        upgrade_database(database)
        initialize(database)
        with database.write() as connection:
            metadata.create_all(connection)
            for table in (tables.videos, tables.jobs, runs):
                if connection.scalar(sa.select(sa.func.count()).select_from(table)):
                    raise ValueError("Cannot bind existing application data")
            record = dict(expected, pair_id=str(uuid4()))
            chroma.mkdir(parents=True, exist_ok=True)
            # Exclusive creation cannot overwrite another pair's marker.
            with (chroma / MARKER).open("x", encoding="utf-8") as stream:
                json.dump(record, stream, sort_keys=True)
            connection.execute(binding.insert().values(id=1, data=record))
        return record
    finally:
        database.close()
