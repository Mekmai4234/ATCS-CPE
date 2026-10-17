"""Explicit offline maintenance; API/worker processes must be stopped first."""

import time

import sqlalchemy as sa
from youtube_backend import database as db

from .errors import error


class MaintenanceExecution:
    def __init__(self, database, *, timeout=600):
        self.database = database
        self.deadline = time.time() + timeout

    @property
    def remaining_seconds(self):
        return max(0, self.deadline - time.time())

    def _idle(self, connection):
        if connection.scalar(
            sa.select(sa.func.count())
            .select_from(db.jobs)
            .where(db.jobs.c.state.in_(["queued", "running"]))
        ):
            raise error("maintenance_busy", "Finish/cancel queued jobs and stop API/workers first")

    def check(self):
        if self.remaining_seconds <= 0:
            raise error("task_timeout", "Maintenance deadline exceeded", status=504)
        with self.database.read() as connection:
            self._idle(connection)

    def authorize(self, sources):
        self.check()
        if not sources or len({s.video_id for s in sources}) != len(sources):
            raise error("invalid_scope", "Provide distinct explicit source videos")
        with self.database.read() as connection:
            for source in sources:
                self._source(connection, source)

    def _source(self, connection, source):
        video = (
            connection.execute(sa.select(db.videos).where(db.videos.c.video_id == source.video_id))
            .mappings()
            .first()
        )
        if (
            not video
            or video["status"] != "ready"
            or (
                video["generation"] != source.generation
                or video["transcript_version"] != source.transcript_version
            )
        ):
            raise error("source_changed", "Maintenance requires the current ready transcript")

    def fence(self, connection, source, *, delete=False):
        if delete:
            raise error("invalid_operation", "Use the durable backend deletion job")
        self._idle(connection)
        self._source(connection, source)
        if self.remaining_seconds <= 0:
            raise error("task_timeout", "Maintenance deadline exceeded", status=504)
