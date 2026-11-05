"""Private per-job checkpoints for multi-step analysis, so a retry resumes finished steps.

A summary or comparison makes several model calls in sequence. When a late call fails with
a retryable provider error the job is requeued, and without checkpoints the retry repeats
every earlier call. Each finished per-video batch is kept here, bound to the job, its owner,
the frozen source version and the exact model input, and read back only by the same job.
"""

import json
import time

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert

from . import database as db
from .errors import AppError
from .repository import digest, row

VERSION = "answer-checkpoint-v1"
# Retries of a quota-parked job can wait until the next provider day.
TTL_SECONDS = 86400
MAX_BYTES = 100_000
KINDS = {"analysis", "research"}


class AnswerCheckpointStore:
    def __init__(self, context):
        self.context = context
        self.repo = context.repository

    def _guard(self, c, source):
        self.context.check()
        job = self.repo._owned(c, self.context.job_id, self.context.lease_token)
        if not job["owner_id"]:
            raise AppError("authentication_required", "Checkpoints require a member", 401)
        if job["kind"] not in KINDS or source.model_dump() not in job["payload"].get("sources", []):
            raise AppError("invalid_scope", "Checkpoint is outside the durable job", 403)
        self.repo._check_sources(c, [source.model_dump()], owner=job["owner_id"])
        return job

    def _key(self, job, source, input_hash):
        return digest([VERSION, job["owner_id"], job["job_id"], source.model_dump(), input_hash])

    @staticmethod
    def _valid_hash(input_hash):
        if len(input_hash) != 64 or any(ch not in "0123456789abcdef" for ch in input_hash):
            raise AppError("cache_invalid", "A canonical request hash is required", 422)

    def load(self, source, input_hash):
        self._valid_hash(input_hash)
        with self.repo.db.read() as c:
            job = self._guard(c, source)
            table = db.v2["cache"]
            record = row(
                c,
                table,
                sa.and_(
                    table.c.cache_id == self._key(job, source, input_hash),
                    table.c.owner_id == job["owner_id"],
                    table.c.expires_at > time.time(),
                ),
            )
            return record["data"] if record else None

    def save(self, source, input_hash, model, data):
        self._valid_hash(input_hash)
        if len(json.dumps(data).encode()) > MAX_BYTES:
            # Too large to keep is not an error: the retry simply repeats this step.
            return False
        with self.repo.db.write() as c:
            job = self._guard(c, source)
            table = db.v2["cache"]
            now = time.time()
            c.execute(
                table.delete().where(table.c.prompt_version == VERSION, table.c.expires_at <= now)
            )
            c.execute(
                insert(table)
                .values(
                    cache_id=self._key(job, source, input_hash),
                    owner_id=job["owner_id"],
                    video_id=source.video_id,
                    generation=source.generation,
                    evidence_version=source.transcript_version,
                    prompt_version=VERSION,
                    model=model,
                    input_hash=input_hash,
                    data=data,
                    expires_at=now + TTL_SECONDS,
                )
                .on_conflict_do_update(
                    index_elements=[table.c.cache_id],
                    set_={"data": data, "expires_at": now + TTL_SECONDS},
                )
            )
            return True
