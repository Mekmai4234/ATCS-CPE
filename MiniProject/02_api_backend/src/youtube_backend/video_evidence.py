"""Private native-video observations, bound to reconciled provider calls and source versions."""

import json
import time

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert

from . import database as db
from .errors import AppError
from .repository import digest, row

VERSION = "youtube-video-v1"


class VideoEvidenceStore:
    def __init__(self, context):
        self.context = context
        self.repo = context.repository

    def guard(self, c, source):
        self.context.check()
        job = self.repo._owned(c, self.context.job_id, self.context.lease_token)
        if not self.context.settings.auth_enabled or not job["owner_id"]:
            raise AppError("authentication_required", "Native video requires a member", 401)
        if job["kind"] not in {
            "chat",
            "analysis",
            "artifact",
            "research",
        } or source.model_dump() not in job["payload"].get("sources", []):
            raise AppError("invalid_scope", "Video is outside the durable job", 403)
        self.repo._check_sources(c, [source.model_dump()], owner=job["owner_id"])
        return job

    def key(self, owner, source, model, question):
        return digest([VERSION, owner, source.model_dump(), model, question])

    def load(self, source, model, question):
        with self.repo.db.read() as c:
            job = self.guard(c, source)
            key = self.key(job["owner_id"], source, model, question)
            table = db.v2["cache"]
            pointer = row(
                c,
                table,
                sa.and_(
                    table.c.cache_id == digest(["lookup", key]), table.c.expires_at > time.time()
                ),
            )
            if pointer:
                revision_id = pointer["data"]["revision_id"]
                record = row(c, table, table.c.cache_id == revision_id)
                if record and record["owner_id"] == job["owner_id"]:
                    return revision_id, record["data"]
            record = row(
                c, table, sa.and_(table.c.cache_id == key, table.c.expires_at > time.time())
            )
            return (key, record["data"]) if record else (key, None)

    def publish(self, source, model, question, data, reservation_id, input_hash):
        if len(json.dumps(data).encode()) > 100_000:
            raise AppError(
                "analysis_budget_exceeded", "Video observations exceed storage budget", 422
            )
        with self.repo.db.write() as c:
            job = self.guard(c, source)
            proof = row(
                c, db.v2["reservations"], db.v2["reservations"].c.reservation_id == reservation_id
            )
            if not proof or any(
                (
                    proof["state"] != "completed",
                    proof["job_id"] != self.context.job_id,
                    proof["lease_token"] != self.context.lease_token,
                    proof["endpoint"] != "generateContent",
                    proof["role"] != "vision",
                    proof["model"] != model,
                    proof["input_hash"] != input_hash,
                    proof["returned_model"] not in proof["returned_allowlist"],
                )
            ):
                raise AppError(
                    "vision_budget_required", "A reconciled native video call is required", 403
                )
            key = self.key(job["owner_id"], source, model, question)
            table = db.v2["cache"]
            value = dict(data, source=source.model_dump(), reservation_id=reservation_id)
            revision_id = digest([key, reservation_id, value])
            fields = dict(
                owner_id=job["owner_id"],
                video_id=source.video_id,
                generation=source.generation,
                evidence_version=source.transcript_version,
                model=model,
                input_hash=input_hash,
                expires_at=time.time() + 3600,
            )
            c.execute(
                insert(table)
                .values(cache_id=revision_id, prompt_version=VERSION, data=value, **fields)
                .on_conflict_do_nothing()
            )
            pointer_data = {"revision_id": revision_id}
            c.execute(
                insert(table)
                .values(
                    cache_id=digest(["lookup", key]),
                    prompt_version=VERSION + "-lookup",
                    data=pointer_data,
                    **fields,
                )
                .on_conflict_do_update(
                    index_elements=[table.c.cache_id],
                    set_={"data": pointer_data, "expires_at": fields["expires_at"]},
                )
            )
            return revision_id

    def resolve(self, citations):
        """Return full authorized observations; display titles are never evidence."""
        self.context.check()
        with self.repo.db.read() as c:
            job = self.repo._owned(c, self.context.job_id, self.context.lease_token)
            return [
                dict(
                    verify_video_citation(self.repo, c, job, citation),
                    evidence_id=citation.chunk_id,
                    video_id=citation.video_id,
                )
                for citation in citations
            ]


def verify_video_citation(repo, c, job, citation):
    """Called again inside the final publication transaction, including cached reads."""
    record = row(c, db.v2["cache"], db.v2["cache"].c.cache_id == citation.observation_cache_id)
    sources = job["payload"].get("sources", [])
    if (
        not record
        or record["owner_id"] != job["owner_id"]
        or record["prompt_version"] != VERSION
        or record["data"].get("source") not in sources
    ):
        raise AppError(
            "invalid_citation", "Video observation is outside this private source scope", 502
        )
    source = record["data"]["source"]
    repo._check_sources(c, [source], owner=job["owner_id"])
    observations = record["data"].get("observations", [])
    match = next((o for o in observations if digest(o) == citation.chunk_id), None)
    if (
        not match
        or citation.video_id != source["video_id"]
        or citation.start_seconds != match["start_seconds"]
        or citation.end_seconds != match["end_seconds"]
    ):
        raise AppError("invalid_citation", "Video citation does not match stored observations", 502)
    return dict(match)
