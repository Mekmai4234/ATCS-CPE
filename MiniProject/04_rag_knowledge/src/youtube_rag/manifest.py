"""Module-owned publication manifest, in the SAME SQLite DB as backend lifecycle/leases.

Chroma records are immutable staging data until this manifest commits. Publication uses
the backend's BEGIN IMMEDIATE transaction, preventing a check/write race with cancellation,
lease recovery and deletion. No changes to backend tables or migrations are needed.
"""

import time

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert
from youtube_backend import database as backend_db
from youtube_backend.schemas import Source

from .errors import error
from .models import Chunk, source_key

metadata = sa.MetaData()
schema = sa.Table(
    "rag04_schema",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("version", sa.Integer, nullable=False),
)
runs = sa.Table(
    "rag04_runs",
    metadata,
    sa.Column("run_id", sa.String, primary_key=True),
    sa.Column("video_id", sa.String, nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("source_key", sa.String, nullable=False),
    sa.Column("source", sa.JSON, nullable=False),
    sa.Column("config", sa.String, nullable=False),
    sa.Column("collection", sa.String, nullable=False),
    sa.Column("state", sa.String, nullable=False),
    sa.Column("created_at", sa.Float, nullable=False),
    sa.Column("chunk_count", sa.Integer, nullable=False),
)
active = sa.Table(
    "rag04_active",
    metadata,
    sa.Column("video_id", sa.String, primary_key=True),
    sa.Column("generation", sa.Integer, primary_key=True),
    sa.Column("run_id", sa.ForeignKey("rag04_runs.run_id"), nullable=False),
)
chunks = sa.Table(
    "rag04_chunks",
    metadata,
    sa.Column("run_id", sa.ForeignKey("rag04_runs.run_id"), primary_key=True),
    sa.Column("chunk_id", sa.String, primary_key=True),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("data", sa.JSON, nullable=False),
    sa.UniqueConstraint("run_id", "ordinal"),
)


def initialize(database):
    """Explicit, additive module-04 schema v1 setup; never alter backend migrations."""
    with database.write() as connection:
        metadata.create_all(connection)
        version = connection.scalar(sa.select(schema.c.version).where(schema.c.id == 1))
        if version is not None and version != 1:
            raise error("index_schema_mismatch", "Unsupported module 04 schema version")
        connection.execute(insert(schema).values(id=1, version=1).on_conflict_do_nothing())


class BackendExecution:
    def __init__(self, context):
        self.context = context

    @property
    def remaining_seconds(self):
        return self.context.remaining_seconds

    def check(self):
        self.context.check()

    def authorize(self, sources):
        self.check()
        job = self.context.repository.check_execution(self.context.job_id, self.context.lease_token)
        if not sources or len({s.video_id for s in sources}) != len(sources):
            raise error("invalid_scope", "Provide a nonempty set of distinct authorized sources")
        if job["kind"] == "import":
            allowed = [
                dict(
                    video_id=job["video_id"],
                    generation=job["generation"],
                    transcript_version=self._import_version(job["video_id"]),
                )
            ]
        else:
            allowed = job["payload"].get("sources", [])
        if any(source.model_dump() not in allowed for source in sources):
            raise error("invalid_scope", "Sources exceed the current job's authorized scope")

    def _import_version(self, video_id):
        with self.context.repository.db.read() as connection:
            return connection.scalar(
                sa.select(backend_db.videos.c.transcript_version).where(
                    backend_db.videos.c.video_id == video_id
                )
            )

    def fence(self, connection, source, *, delete=False):
        ctx = self.context
        # This intentionally uses the v0.1 backend transaction-level lease guard. A separate
        # context.check() read would not make publication atomic. Covered by integration tests.
        job = ctx.repository._owned(connection, ctx.job_id, ctx.lease_token)
        if time.time() >= ctx.deadline_at:
            raise error("task_timeout", "Task exceeded its deadline", retryable=True, status=504)
        video = (
            connection.execute(
                sa.select(backend_db.videos).where(backend_db.videos.c.video_id == source.video_id)
            )
            .mappings()
            .first()
        )
        if not video or video["generation"] != source.generation:
            raise error("source_changed", "Video generation has changed")
        if job["video_id"] != source.video_id or job["generation"] != source.generation:
            raise error("invalid_scope", "Job does not authorize this video generation")
        if delete:
            valid = job["kind"] == "delete" and video["status"] == "deleting"
        else:
            valid = (
                job["kind"] == "import"
                and video["status"] == "indexing"
                and video["transcript_version"] == source.transcript_version
            )
        if not valid:
            raise error("source_changed", "Video lifecycle no longer authorizes this operation")


class Manifest:
    def __init__(self, database):
        self.database = database
        with database.read() as connection:
            try:
                version = connection.scalar(sa.select(schema.c.version).where(schema.c.id == 1))
            except sa.exc.OperationalError:
                raise error(
                    "index_schema_missing", "Run yk-rag init before starting module 04"
                ) from None
        if version != 1:
            raise error("index_schema_mismatch", "Unsupported module 04 schema version")

    def current(self, sources, config, *, require=False):
        records, missing = [], []
        with self.database.read() as connection:
            for source in sources:
                row = (
                    connection.execute(
                        sa.select(runs)
                        .join(active, runs.c.run_id == active.c.run_id)
                        .where(
                            active.c.video_id == source.video_id,
                            active.c.generation == source.generation,
                        )
                    )
                    .mappings()
                    .first()
                )
                if not row or row["source_key"] != source_key(source):
                    missing.append(source)
                    continue
                if row["config"] != config:
                    raise error(
                        "index_configuration_mismatch",
                        "Index configuration changed; explicitly reindex selected videos",
                    )
                records.append(dict(row))
        if require and missing:
            raise error("index_incomplete", "Selected sources have missing or replaced indexes")
        return records, missing

    def register(self, run_id, source, settings, count, execution):
        execution.check()
        with self.database.write() as connection:
            execution.fence(connection, source)
            connection.execute(
                runs.insert().values(
                    run_id=run_id,
                    video_id=source.video_id,
                    generation=source.generation,
                    source_key=source_key(source),
                    source=source.model_dump(),
                    config=settings.fingerprint,
                    collection=settings.collection_name,
                    state="staging",
                    created_at=time.time(),
                    chunk_count=count,
                )
            )

    def publish(self, run_id, source, records, execution):
        with self.database.write() as connection:
            execution.fence(connection, source)
            previous = connection.scalar(
                sa.select(active.c.run_id).where(
                    active.c.video_id == source.video_id, active.c.generation == source.generation
                )
            )
            if previous:
                connection.execute(
                    runs.update().where(runs.c.run_id == previous).values(state="retired")
                )
            connection.execute(
                chunks.insert(),
                [
                    dict(run_id=run_id, chunk_id=c.chunk_id, ordinal=c.ordinal, data=c.model_dump())
                    for c in records
                ],
            )
            connection.execute(
                runs.update().where(runs.c.run_id == run_id).values(state="published")
            )
            connection.execute(
                insert(active)
                .values(video_id=source.video_id, generation=source.generation, run_id=run_id)
                .on_conflict_do_update(
                    index_elements=[active.c.video_id, active.c.generation], set_={"run_id": run_id}
                )
            )
            # Metadata insertion itself must not consume the remaining lease/deadline.
            execution.fence(connection, source)

    def page(self, run_ids, offset, limit):
        if not run_ids:
            return []
        with self.database.read() as connection:
            data = (
                connection.execute(
                    sa.select(chunks.c.data)
                    .join(runs, runs.c.run_id == chunks.c.run_id)
                    .where(chunks.c.run_id.in_(run_ids))
                    .order_by(runs.c.video_id, runs.c.generation, chunks.c.ordinal)
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
        return [Chunk.model_validate(item) for item in data]

    def by_ids(self, run_ids, ids):
        if not run_ids or not ids:
            return []
        with self.database.read() as connection:
            data = (
                connection.execute(
                    sa.select(chunks.c.data).where(
                        chunks.c.run_id.in_(run_ids), chunks.c.chunk_id.in_(ids)
                    )
                )
                .scalars()
                .all()
            )
        return [Chunk.model_validate(item) for item in data]

    def begin_delete(self, video_id, generation, execution):
        source = Source(video_id=video_id, generation=generation, transcript_version="delete")
        with self.database.write() as connection:
            execution.fence(connection, source, delete=True)
            connection.execute(
                active.delete().where(
                    active.c.video_id == video_id, active.c.generation <= generation
                )
            )
            condition = sa.and_(runs.c.video_id == video_id, runs.c.generation <= generation)
            connection.execute(runs.update().where(condition).values(state="deleting"))
            return [
                dict(row) for row in connection.execute(sa.select(runs).where(condition)).mappings()
            ]

    def garbage(self, *, include_staging=False):
        states = ["retired", "deleting"] + (["staging"] if include_staging else [])
        with self.database.read() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    sa.select(runs).where(runs.c.state.in_(states))
                ).mappings()
            ]

    def forget(self, run_id):
        with self.database.write() as connection:
            if connection.scalar(sa.select(active.c.run_id).where(active.c.run_id == run_id)):
                raise error("active_index", "Cannot remove an active index")
            connection.execute(chunks.delete().where(chunks.c.run_id == run_id))
            connection.execute(runs.delete().where(runs.c.run_id == run_id))
