"""Module-owned publication manifest, in the SAME SQLite DB as backend lifecycle/leases.

Chroma records are immutable staging data until this manifest commits. Publication uses
the backend's BEGIN IMMEDIATE transaction, preventing a check/write race with cancellation,
lease recovery and deletion. No changes to backend tables or migrations are needed.
"""

import secrets
import time

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert
from youtube_backend import database as backend_db
from youtube_backend.schemas import Source

from .authorization import authenticated, permission_scope, readers, references
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
store_binding = sa.Table(
    "rag04_store_binding",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("store_id", sa.String, nullable=False),
)
security = sa.Table(
    "rag04_security",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("cursor_key", sa.String, nullable=False),
)


def initialize(database):
    """Explicit, additive module-04 schema v1 setup; never alter backend migrations."""
    with database.write() as connection:
        metadata.create_all(connection)
        from .embedding_cache import cache_metadata
        from .media_manifest import media_metadata

        cache_metadata.create_all(connection)
        media_metadata.create_all(connection)
        version = connection.scalar(sa.select(schema.c.version).where(schema.c.id == 1))
        if version is not None and version != 1:
            raise error("index_schema_mismatch", "Unsupported module 04 schema version")
        connection.execute(insert(schema).values(id=1, version=1).on_conflict_do_nothing())
        connection.execute(
            insert(security).values(id=1, cursor_key=secrets.token_hex(32)).on_conflict_do_nothing()
        )


class BackendExecution:
    def __init__(self, context):
        self.context = context

    @property
    def remaining_seconds(self):
        return self.context.remaining_seconds

    def check(self):
        authenticated(self.context.settings)
        self.context.check()

    def permission_scope(self, sources, *, operation="read"):
        return permission_scope(self.context, sources, operation=operation)

    def authorize_index(self, source, *, allow_reindex=False):
        job = self.context.repository.check_execution(self.context.job_id, self.context.lease_token)
        if job["kind"] != "import" or allow_reindex:
            raise error(
                "invalid_operation",
                "Index/reindex requires an import worker or stopped operator",
                status=403,
            )

    def authorize_cleanup(self, *, source=None, include_staging=False):
        self.check()
        job = self.context.repository.check_execution(self.context.job_id, self.context.lease_token)
        if job["kind"] != "import" or source is None or include_staging:
            raise error(
                "invalid_operation",
                "Only scoped import cleanup or stopped maintenance is permitted",
                status=403,
            )

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
        if authenticated(self.context.settings) and job["kind"] != "import":
            authorize = getattr(self.context, "authorize_sources", None)
            if not callable(authorize):
                raise error(
                    "authorization_unavailable", "Trusted source authorizer is required", status=503
                )
            authorize(sources)

    async def gemini_call(self, callback, *, credential_sha256=None, **request):
        if credential_sha256 is None:
            raise error(
                "gemini_broker_required", "A bound embedding credential is required", status=503
            )
        self.embedding_policy(request["model"], credential_sha256)
        call = getattr(self.context, "gemini_call", None)
        if not callable(call):
            raise error(
                "gemini_broker_required", "Install the execution-bound 02 broker", status=503
            )
        return await call(callback, **request)

    def cache_scope(self, sources):
        self.authorize(sources)
        self.permission_scope(sources)
        job = self.context.repository.check_execution(self.context.job_id, self.context.lease_token)
        return {"owner": job.get("owner_id"), "sources": [s.model_dump() for s in sources]}

    def embedding_policy(self, model, credential_sha256):
        from youtube_backend.quota import QuotaBroker

        broker = QuotaBroker(self.context.repository)
        policy, _ = broker.access(model, "embedContent", "embedding")
        broker.access(model, "countTokens", "embedding")
        if credential_sha256 != policy.key_sha256:
            raise error(
                "free_tier_unverified",
                "Embedding credential differs from the approved project",
                status=503,
            )
        # An alias/returned-model review or policy renewal invalidates checkpoints.
        # Public model names alone cannot establish identical embedding semantics.
        return broker.fingerprint(policy)

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
            if references(connection, source.video_id) or readers(
                connection, source.video_id, except_job=job["job_id"]
            ):
                raise error("source_in_use", "Source still has library references or active jobs")
        else:
            valid = (
                job["kind"] == "import"
                and video["status"] == "indexing"
                and video["transcript_version"] == source.transcript_version
            )
        if not valid:
            raise error("source_changed", "Video lifecycle no longer authorizes this operation")

    def cleanup_fence(self, connection, row):
        ctx = self.context
        job = ctx.repository._owned(connection, ctx.job_id, ctx.lease_token)
        if time.time() >= ctx.deadline_at:
            raise error("task_timeout", "Task exceeded its deadline", status=504)
        valid_generation = (
            row["generation"] <= job["generation"]
            if job["kind"] == "delete"
            else row["generation"] == job["generation"]
        )
        if (
            job["kind"] not in {"import", "delete"}
            or job["video_id"] != row["video_id"]
            or not valid_generation
        ):
            raise error(
                "invalid_operation",
                "User retrieval jobs cannot perform central maintenance",
                status=403,
            )
        return job["job_id"]


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

    def has_published_media(self):
        from .media_manifest import media_runs

        with self.database.read() as connection:
            if not sa.inspect(connection).has_table(media_runs.name):
                return False
            return bool(
                connection.scalar(
                    sa.select(media_runs.c.run_id)
                    .where(media_runs.c.state.in_(["published", "retired"]))
                    .limit(1)
                )
            )

    def binding(self):
        with self.database.read() as connection:
            try:
                return connection.scalar(
                    sa.select(store_binding.c.store_id).where(store_binding.c.id == 1)
                )
            except sa.exc.OperationalError:
                raise error(
                    "index_schema_missing", "Run yk-rag init to add the store binding table"
                ) from None

    def cursor_key(self):
        with self.database.read() as connection:
            try:
                value = connection.scalar(
                    sa.select(security.c.cursor_key).where(security.c.id == 1)
                )
            except sa.exc.OperationalError:
                value = None
        if not value:
            raise error(
                "index_schema_missing", "Run stopped yk-rag init to add cursor signing state"
            )
        return bytes.fromhex(value)

    def all_runs(self, connection=None):
        if connection is None:
            with self.database.read() as reader:
                return self.all_runs(reader)
        return [
            dict(row)
            for row in connection.execute(sa.select(runs).order_by(runs.c.run_id)).mappings()
        ]

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

    def _removal_guard(self, connection, row, execution):
        job_id = execution.cleanup_fence(connection, row)
        if connection.scalar(sa.select(active.c.run_id).where(active.c.run_id == row["run_id"])):
            raise error("active_index", "Cannot remove an active index")
        if readers(connection, row["video_id"], except_job=job_id):
            raise error("source_in_use", "Active jobs still reference this source")
        if row["state"] == "deleting" and references(connection, row["video_id"]):
            raise error("source_in_use", "Source still belongs to a library")

    def check_removal(self, row, execution):
        with self.database.write() as connection:
            current = (
                connection.execute(sa.select(runs).where(runs.c.run_id == row["run_id"]))
                .mappings()
                .first()
            )
            if current is not None:
                self._removal_guard(connection, current, execution)

    def forget(self, run_id, execution):
        with self.database.write() as connection:
            row = (
                connection.execute(sa.select(runs).where(runs.c.run_id == run_id))
                .mappings()
                .first()
            )
            if row is None:
                return
            self._removal_guard(connection, row, execution)
            connection.execute(chunks.delete().where(chunks.c.run_id == run_id))
            connection.execute(runs.delete().where(runs.c.run_id == run_id))
