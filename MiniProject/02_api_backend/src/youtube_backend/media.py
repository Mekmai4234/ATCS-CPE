"""Authorized immutable image assets and versioned OCR/visual source snapshots.

Only a durable import/enrichment lease may publish bytes. No public directory,
browser path, external asset URL or synthetic transcript is accepted.
"""

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert

from . import database as db
from .config import PROJECT_ROOT
from .errors import AppError
from .evidence_v2 import MediaEnrichment, SourceSnapshotV2, VisualCitationV2
from .repository import digest, row


def asset_root(settings):
    path = Path(settings.media_asset_dir).expanduser()
    base = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
    return (base / digest(settings.database_url)[:24]).resolve()


class MediaStore:
    def __init__(self, repository):
        self.repo, self.settings = repository, repository.settings
        # Separate independently configured SQLite stores even if they share a base
        # media directory. Restores use the original database URL recorded by backup.
        self.root = asset_root(self.settings)

    def _video(self, connection, video_id, generation=None):
        if not self.settings.auth_enabled:
            raise AppError("authentication_required", "Media APIs require a member session", 401)
        self.repo._require_video(connection, video_id)
        video = row(connection, db.videos, db.videos.c.video_id == video_id)
        if (
            not video
            or video["status"] in {"deleted", "deleting"}
            or (generation is not None and video["generation"] != generation)
        ):
            raise AppError("video_not_found", "Video not found", 404)
        return video

    def enqueue(self, video_id, *, idempotency_key=None, resume_job=None):
        with self.repo.db.write() as c:
            video = self._video(c, video_id)
            owner = self.repo._actor(c)
            payload = {
                "sources": [],
                "contract_version": 2,
                "max_frames": self.settings.media_max_frames,
                "max_frame_bytes": self.settings.media_max_frame_bytes,
            }
            request_hash = digest([video_id, video["generation"], payload])
            key = digest([owner, "enrich", idempotency_key]) if idempotency_key else None
            if key:
                previous = row(c, db.jobs, db.jobs.c.idempotency_key == key)
                if previous:
                    self.repo._private(c, previous)
                    if previous["request_hash"] != request_hash:
                        raise AppError(
                            "idempotency_conflict", "Key already used with different input", 409
                        )
                    return previous
            if resume_job:
                old = row(c, db.jobs, db.jobs.c.job_id == resume_job)
                self.repo._private(c, old)
                if (
                    not old
                    or old["kind"] != "enrich"
                    or old["state"] not in {"paused", "failed"}
                    or not old["retryable"]
                    or old["generation"] != video["generation"]
                ):
                    raise AppError("retry_not_allowed", "Enrichment cannot be resumed", 409)
            active = row(
                c,
                db.jobs,
                sa.and_(
                    db.jobs.c.video_id == video_id,
                    db.jobs.c.kind == "enrich",
                    db.jobs.c.owner_id == owner,
                    db.jobs.c.generation == video["generation"],
                    db.jobs.c.state.in_(["queued", "running"]),
                ),
            )
            if active:
                return active
            if resume_job:
                # Repeated retry clicks follow one newly consented job, even after it completes.
                payload["resumes"] = resume_job
                next_job = row(
                    c,
                    db.jobs,
                    sa.and_(db.jobs.c.idempotency_key == digest([owner, "resume", resume_job])),
                )
                if next_job:
                    return next_job
                key = digest([owner, "resume", resume_job])
            state = db.v2["media_states"]
            c.execute(
                insert(state)
                .values(
                    video_id=video_id,
                    generation=video["generation"],
                    state="pending",
                    updated_at=time.time(),
                )
                .on_conflict_do_update(
                    index_elements=[state.c.video_id, state.c.generation],
                    set_={"state": "pending", "error_code": None, "updated_at": time.time()},
                )
            )
            available_at = time.time()
            if resume_job:
                wait = row(c, db.v2["pauses"], db.v2["pauses"].c.job_id == resume_job)
                if wait:
                    when = (
                        wait["data"].get("retry_at")
                        if wait["data"].get("time_source") == "provider"
                        else None
                    )
                    if when:
                        available_at = max(available_at, datetime.fromisoformat(when).timestamp())
            return self.repo._new_job(
                c,
                "enrich",
                payload,
                video_id=video_id,
                generation=video["generation"],
                idempotency_key=key,
                request_hash=request_hash,
                available_at=available_at,
            )

    def publish(self, context, bundle):
        bundle = MediaEnrichment.model_validate(bundle)
        if len(bundle.frames) > self.settings.media_max_frames:
            raise AppError("media_limit", "Too many sampled frames", 422)
        frames, assets, revisions, states = (
            db.v2[k] for k in ("frames", "assets", "revisions", "media_states")
        )
        with self.repo.db.write() as c:
            job = self.repo._owned(c, context.job_id, context.lease_token)
            if job["kind"] not in {"import", "enrich"}:
                raise AppError("media_publication_denied", "A media worker lease is required", 403)
            if len(bundle.frames) > job["payload"].get(
                "max_frames", self.settings.media_max_frames
            ):
                raise AppError("media_limit", "Frames exceed the frozen execution limit", 422)
            if any(frame.visual_text.strip() for frame in bundle.frames):
                proof = row(
                    c,
                    db.v2["reservations"],
                    db.v2["reservations"].c.reservation_id == bundle.vision_reservation_id,
                )
                if (
                    not proof
                    or proof["state"] != "completed"
                    or proof["job_id"] != context.job_id
                    or proof["lease_token"] != context.lease_token
                    or proof["endpoint"] != "generateContent"
                    or proof["role"] != "vision"
                    or proof["model"] != bundle.requested_model
                    or proof["returned_model"] != bundle.returned_model
                    or proof["returned_model"] not in proof["returned_allowlist"]
                    or proof["input_hash"] != bundle.vision_input_hash
                ):
                    raise AppError(
                        "vision_budget_required",
                        "Visual publication requires this execution's reconciled call",
                        403,
                    )
            video = row(c, db.videos, db.videos.c.video_id == job["video_id"])
            if (
                not video
                or video["generation"] != job["generation"]
                or video["status"] in {"deleting", "deleted"}
            ):
                raise AppError("source_changed", "Media source changed", 409)
            summary = dict(
                source_sha256=bundle.source_sha256,
                sampling_version=bundle.sampling_version,
                ocr_version=bundle.ocr_version,
                prompt_version=bundle.prompt_version,
                duration_seconds=bundle.duration_seconds,
                sampled_timestamps=[f.timestamp_seconds for f in bundle.frames],
                whole_video_reviewed=False,
                frame_ids=[],
                requested_model=bundle.requested_model,
                returned_model=bundle.returned_model,
                vision_reservation_id=bundle.vision_reservation_id,
                vision_input_hash=bundle.vision_input_hash,
            )
            observations = {"ocr": [], "visual": []}
            for frame in bundle.frames:
                data = frame.content
                valid = (
                    (frame.mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
                    or (frame.mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
                    or (
                        frame.mime == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
                    )
                )
                if not valid or len(data) > min(
                    self.settings.media_max_frame_bytes,
                    job["payload"].get("max_frame_bytes", self.settings.media_max_frame_bytes),
                ):
                    raise AppError("media_invalid", "Frame format or size is invalid", 422)
                content_hash = hashlib.sha256(data).hexdigest()
                asset_id = digest([job["video_id"], job["generation"], content_hash])
                frame_id = digest([asset_id, frame.timestamp_seconds, bundle.sampling_version])
                # Hash-only path components; never accept a client or adapter file path.
                relative = f"{digest(job['video_id'])[:24]}/{job['generation']}/{content_hash}"
                target = (self.root / relative).resolve()
                if not target.is_relative_to(self.root):
                    raise AppError("media_invalid", "Asset location is invalid", 422)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(data)
                os.replace(temporary, target)
                c.execute(
                    insert(assets)
                    .values(
                        asset_id=asset_id,
                        video_id=job["video_id"],
                        generation=job["generation"],
                        sha256=content_hash,
                        mime=frame.mime,
                        size=len(data),
                        path=relative,
                        created_at=time.time(),
                    )
                    .on_conflict_do_nothing()
                )
                c.execute(
                    insert(frames)
                    .values(
                        frame_id=frame_id,
                        asset_id=asset_id,
                        video_id=job["video_id"],
                        generation=job["generation"],
                        timestamp_seconds=frame.timestamp_seconds,
                        sampling_version=bundle.sampling_version,
                    )
                    .on_conflict_do_nothing()
                )
                summary["frame_ids"].append(frame_id)
                for kind, text in (("ocr", frame.ocr_text), ("visual", frame.visual_text)):
                    if text.strip():
                        observations[kind].append(
                            dict(
                                frame_id=frame_id,
                                asset_id=asset_id,
                                timestamp_seconds=frame.timestamp_seconds,
                                text=text,
                                asset_url=f"/api/media/assets/{asset_id}",
                            )
                        )
            snapshots = []
            for kind, items in observations.items():
                if not items:
                    continue
                data = dict(items=items, coverage=summary)
                version = digest(data)
                snapshot = SourceSnapshotV2(
                    video_id=job["video_id"],
                    generation=job["generation"],
                    kind=kind,
                    evidence_version=version,
                )
                c.execute(
                    insert(revisions)
                    .values(
                        revision_id=digest(snapshot.model_dump()),
                        video_id=job["video_id"],
                        generation=job["generation"],
                        kind=kind,
                        version=version,
                        data=data,
                        created_at=time.time(),
                    )
                    .on_conflict_do_nothing()
                )
                snapshots.append(snapshot.model_dump())
            summary["snapshots"] = snapshots
            # Bounded disk I/O can still outlast a lease/deadline. Recheck at the
            # publication fence; rolled-back files remain private GC candidates.
            self.repo._owned(c, context.job_id, context.lease_token)
            c.execute(
                insert(states)
                .values(
                    video_id=job["video_id"],
                    generation=job["generation"],
                    state="ready",
                    data=summary,
                    updated_at=time.time(),
                )
                .on_conflict_do_update(
                    index_elements=[states.c.video_id, states.c.generation],
                    set_={
                        "state": "ready",
                        "data": summary,
                        "error_code": None,
                        "updated_at": time.time(),
                    },
                )
            )
            if not video["transcript_version"]:
                c.execute(
                    db.videos.update()
                    .where(db.videos.c.video_id == job["video_id"])
                    .values(status="visual_ready", updated_at=time.time())
                )
            return summary

    def evidence(self, video_id):
        with self.repo.db.read() as c:
            video = self._video(c, video_id)
            state = row(
                c,
                db.v2["media_states"],
                sa.and_(
                    db.v2["media_states"].c.video_id == video_id,
                    db.v2["media_states"].c.generation == video["generation"],
                ),
            )
            result = dict(
                contract_version=2,
                video_id=video_id,
                generation=video["generation"],
                state=state["state"] if state else "not_requested",
                snapshots=[],
                evidence=[],
            )
            if state and state["data"]:
                result["coverage"] = {
                    k: v for k, v in state["data"].items() if k != "vision_reservation_id"
                }
                result["snapshots"] = state["data"].get("snapshots", [])
                for snapshot in result["snapshots"]:
                    revision = row(
                        c, db.v2["revisions"], db.v2["revisions"].c.revision_id == digest(snapshot)
                    )
                    if revision:
                        result["evidence"].extend(
                            dict(
                                item,
                                kind=snapshot["kind"],
                                evidence_version=snapshot["evidence_version"],
                            )
                            for item in revision["data"]["items"]
                        )
            return result

    def asset(self, asset_id):
        with self.repo.db.read() as c:
            asset = row(c, db.v2["assets"], db.v2["assets"].c.asset_id == asset_id)
            if not asset:
                raise AppError("asset_not_found", "Asset not found", 404)
            try:
                self._video(c, asset["video_id"], asset["generation"])
            except AppError as error:
                if error.status_code == 404:
                    raise AppError("asset_not_found", "Asset not found", 404) from None
                raise
            path = (self.root / asset["path"]).resolve()
            if not path.is_relative_to(self.root):
                raise AppError("asset_not_found", "Asset not found", 404)
            try:
                if path.stat().st_size > self.settings.media_max_frame_bytes:
                    raise OSError
                data = path.read_bytes()
            except OSError:
                raise AppError("asset_not_found", "Asset not found", 404) from None
            if len(data) != asset["size"] or hashlib.sha256(data).hexdigest() != asset["sha256"]:
                raise AppError("asset_invalid", "Asset integrity check failed", 409)
            return data, asset["mime"]

    def verify_citation(self, context, citation):
        citation = VisualCitationV2.model_validate(citation)
        snapshot = citation.source
        with self.repo.db.read() as c:
            job = self.repo._owned(c, context.job_id, context.lease_token)
            if (
                job["kind"] != "enrich"
                or job["video_id"] != snapshot.video_id
                or job["generation"] != snapshot.generation
            ):
                raise AppError("invalid_scope", "Visual evidence exceeds this execution scope", 403)
            self.repo._require_video(c, snapshot.video_id, job["owner_id"])
            revision = row(
                c,
                db.v2["revisions"],
                db.v2["revisions"].c.revision_id == digest(snapshot.model_dump()),
            )
            if not revision or not any(
                item["frame_id"] == citation.frame_id
                and item["asset_id"] == citation.asset_id
                and item["timestamp_seconds"] == citation.start_seconds
                and item["text"] == citation.text
                for item in revision["data"]["items"]
            ):
                raise AppError(
                    "invalid_citation", "Visual citation does not match frozen evidence", 502
                )
            return citation

    def cache(self, context, snapshot, prompt_version, model, input_hash, data=None, ttl=3600):
        snapshot = SourceSnapshotV2.model_validate(snapshot)
        if len(input_hash) != 64 or any(ch not in "0123456789abcdef" for ch in input_hash):
            raise AppError("cache_invalid", "A canonical request hash is required", 422)
        with self.repo.db.write() as c:
            job = self.repo._owned(c, context.job_id, context.lease_token)
            if not job["owner_id"]:
                raise AppError("authentication_required", "Private cache owner required", 401)
            if (
                job["kind"] != "enrich"
                or job["video_id"] != snapshot.video_id
                or job["generation"] != snapshot.generation
            ):
                raise AppError("invalid_scope", "Cache exceeds this media execution scope", 403)
            self.repo._require_video(c, snapshot.video_id, job["owner_id"])
            video = row(c, db.videos, db.videos.c.video_id == snapshot.video_id)
            if video["generation"] != snapshot.generation or video["status"] in {
                "deleting",
                "deleted",
            }:
                raise AppError("source_changed", "Media source changed", 409)
            if not row(
                c,
                db.v2["revisions"],
                db.v2["revisions"].c.revision_id == digest(snapshot.model_dump()),
            ):
                raise AppError("source_changed", "Evidence revision missing", 409)
            key = digest(
                [job["owner_id"], snapshot.model_dump(), prompt_version, model, input_hash]
            )
            table = db.v2["cache"]
            if data is not None:
                if len(json.dumps(data)) > 100_000 or not 0 < ttl <= 86400:
                    raise AppError("cache_limit", "Analysis cache entry exceeds its bound", 422)
                c.execute(
                    insert(table)
                    .values(
                        cache_id=key,
                        owner_id=job["owner_id"],
                        video_id=snapshot.video_id,
                        generation=snapshot.generation,
                        evidence_version=snapshot.evidence_version,
                        prompt_version=prompt_version,
                        model=model,
                        input_hash=input_hash,
                        data=data,
                        expires_at=time.time() + ttl,
                    )
                    .on_conflict_do_update(
                        index_elements=[table.c.cache_id],
                        set_={"data": data, "expires_at": time.time() + ttl},
                    )
                )
                return data
            record = row(
                c, table, sa.and_(table.c.cache_id == key, table.c.expires_at > time.time())
            )
            return record["data"] if record else None

    def gc(self, context):
        with self.repo.db.write() as c:
            job = self.repo._owned(c, context.job_id, context.lease_token)
            if job["kind"] != "delete":
                raise AppError("media_gc_denied", "A physical deletion lease is required", 403)
            # claim() already waits for running readers. Recheck memberships at the writer fence.
            if c.scalar(
                sa.select(sa.func.count())
                .select_from(db.user_videos)
                .where(db.user_videos.c.video_id == job["video_id"])
            ):
                raise AppError("source_in_use", "Media still belongs to a library", 409)
            assets = db.v2["assets"]
            selected = list(
                c.execute(
                    sa.select(assets).where(
                        assets.c.video_id == job["video_id"],
                        assets.c.generation <= job["generation"],
                    )
                ).mappings()
            )
            for key in ("cache", "revisions", "frames"):
                table = db.v2[key]
                c.execute(
                    table.delete().where(
                        table.c.video_id == job["video_id"], table.c.generation <= job["generation"]
                    )
                )
            for asset in selected:
                path = (self.root / asset["path"]).resolve()
                if not path.is_relative_to(self.root):
                    raise AppError("media_invalid", "Asset location is invalid", 409)
                path.unlink(missing_ok=True)
                path.with_suffix(".tmp").unlink(missing_ok=True)
            c.execute(
                assets.delete().where(
                    assets.c.video_id == job["video_id"], assets.c.generation <= job["generation"]
                )
            )
            states = db.v2["media_states"]
            c.execute(
                states.delete().where(
                    states.c.video_id == job["video_id"], states.c.generation <= job["generation"]
                )
            )
            namespace = (self.root / digest(job["video_id"])[:24]).resolve()
            if not namespace.is_relative_to(self.root):
                raise AppError("media_invalid", "Asset namespace is invalid", 409)
            if namespace.exists():
                # Also remove hash-named files from an interrupted publication whose
                # SQLite transaction rolled back. Never recurse or traverse symlinks.
                for generation in namespace.iterdir():
                    if not generation.name.isdecimal() or int(generation.name) > job["generation"]:
                        continue
                    if not generation.resolve().is_relative_to(namespace):
                        raise AppError("media_invalid", "Asset generation is invalid", 409)
                    for path in generation.iterdir():
                        stem = path.name.removesuffix(".tmp")
                        if len(stem) == 64 and all(ch in "0123456789abcdef" for ch in stem):
                            if not path.resolve().is_relative_to(generation.resolve()):
                                raise AppError("media_invalid", "Asset location is invalid", 409)
                            path.unlink(missing_ok=True)
                    if not any(generation.iterdir()):
                        generation.rmdir()
