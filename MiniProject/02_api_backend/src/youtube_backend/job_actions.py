"""Explicit fresh work and opt-in isolated-trial reindex; history GETs are read-only."""

import sqlalchemy as sa

from . import database as db
from .admin import require_admin
from .errors import AppError
from .local_inference import execution_identity
from .repository import ACTIVE, digest


def required_key(key):
    if not key:
        raise AppError("idempotency_required", "An Idempotency-Key is required", 422)


def trial_reindex(repo, video_id, key):
    required_key(key)
    if (
        not repo.settings.trial_reindex_enabled
        or repo.settings.app_env not in {"test", "development"}
        or not repo.settings.auth_enabled
    ):
        raise AppError(
            "trial_reindex_disabled", "Use an opted-in authenticated paired trial store", 409
        )
    with repo.db.write() as c:
        owner = repo._actor(c)
        require_admin(c)
        sources = repo._sources(c, {"video_ids": [video_id]})
        execution = execution_identity(repo.settings)
        fingerprint = digest([sources, execution])
        replay_key = digest([owner, "trial-reindex", key])
        previous = repo._replay_job(c, replay_key, fingerprint)
        if previous:
            return previous
        if c.scalar(
            sa.select(db.jobs.c.job_id)
            .where(
                db.jobs.c.kind == "reindex",
                db.jobs.c.video_id == video_id,
                db.jobs.c.state.in_(ACTIVE),
            )
            .limit(1)
        ):
            raise AppError("reindex_busy", "A trial index job already exists", 409)
        return repo._new_job(
            c,
            "reindex",
            {
                "sources": sources,
                "execution": execution,
                "request": {"scope": {"video_ids": [video_id]}},
            },
            video_id=video_id,
            generation=sources[0]["generation"],
            idempotency_key=replay_key,
            request_hash=fingerprint,
        )


def regenerate(repo, job_id, key, allowed):
    required_key(key)
    original = repo.get_job(job_id)
    if original["kind"] not in allowed or original["kind"] not in {"artifact", "research"}:
        raise AppError(
            "regenerate_unsupported", "The mounted adapter has no fresh-generation contract", 409
        )
    with repo.db.write() as c:
        repo._private(c, original)
        execution = execution_identity(repo.settings)
        request = original["payload"]["request"]
        fingerprint = digest([job_id, request, original["payload"]["sources"], execution])
        replay_key = digest([original["owner_id"], "regenerate", key])
        previous = repo._replay_job(c, replay_key, fingerprint)
        if previous:
            repo._check_sources(c, previous["payload"]["sources"], owner=original["owner_id"])
            return previous
        if original["state"] not in {"completed", "partial"}:
            raise AppError(
                "regenerate_not_allowed", "Open saved completed work before regenerating", 409
            )
        repo._check_sources(c, original["payload"]["sources"], owner=original["owner_id"])
        return repo._new_job(
            c,
            original["kind"],
            {
                "request": request,
                "sources": original["payload"]["sources"],
                "execution": execution,
                "bypass_cache": True,
                "regenerates": job_id,
            },
            idempotency_key=replay_key,
            request_hash=fingerprint,
        )
