import hashlib
import json
import math
import random
import time
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from . import database as db
from .errors import AppError, LeaseLost
from .ownership import Ownership
from .schemas import Scope, Source, TranscriptResult
from .telemetry import request_id
from .urls import canonical_url, normalize_url

ACTIVE = {"queued", "running"}
TERMINAL = {"completed", "partial", "failed", "cancelled"}


def uid():
    return str(uuid4())


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def row(connection, table, condition):
    result = connection.execute(sa.select(table).where(condition)).mappings().first()
    return dict(result) if result else None


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value is not None else None


class Repository(Ownership):
    def __init__(self, database, settings):
        self.db = database
        self.settings = settings

    def _message_timestamp(self, connection, conversation_id):
        """Preserve insertion order when the host clock returns equal timestamps.

        Call only inside the serialized writer transaction that inserts the message.
        UUID ordering cannot represent causality between a user turn and its answer.
        """
        previous = connection.scalar(
            sa.select(sa.func.max(db.messages.c.created_at)).where(
                db.messages.c.conversation_id == conversation_id
            )
        )
        now = time.time()
        return now if previous is None else max(now, math.nextafter(previous, math.inf))

    def _check_mode(self, connection):
        modes = (
            connection.execute(sa.select(db.jobs.c.payload["adapter_mode"].as_string()).distinct())
            .scalars()
            .all()
        )
        if any(mode and mode != self.settings.adapter_mode for mode in modes):
            raise AppError(
                "adapter_mode_mismatch",
                "Use a separate DATABASE_URL when switching between fixture and other adapters",
                409,
            )
        if self.settings.adapter_mode == "custom":
            identities = (
                connection.execute(
                    sa.select(db.jobs.c.payload["adapter_identity"].as_string())
                    .where(db.jobs.c.payload["adapter_mode"].as_string() == "custom")
                    .distinct()
                )
                .scalars()
                .all()
            )
            if any(identity != self.adapter_identity for identity in identities):
                raise AppError(
                    "adapter_mode_mismatch",
                    "Use a separate DATABASE_URL for this adapter profile",
                    409,
                )

    @property
    def adapter_identity(self):
        return f"{self.settings.adapter_factory}:{self.settings.backend_integration_profile}"

    def check_mode(self):
        with self.db.read() as connection:
            self._check_mode(connection)

    def _new_job(self, connection, kind, payload, **extra):
        self._check_mode(connection)
        payload = dict(
            payload,
            adapter_mode=self.settings.adapter_mode,
            adapter_identity=self.adapter_identity
            if self.settings.adapter_mode == "custom"
            else None,
        )
        now = time.time()
        data = dict(
            job_id=uid(),
            request_id=request_id.get() or uid(),
            kind=kind,
            state="queued",
            stage="queued",
            payload=payload,
            retryable=False,
            attempt_count=0,
            max_attempts=1 if kind == "research" else self.settings.job_max_attempts,
            available_at=now,
            cancel_requested=False,
            created_at=now,
            updated_at=now,
        )
        data["owner_id"] = self._actor(connection)
        data.update(extra)
        connection.execute(db.jobs.insert().values(**data))
        return row(connection, db.jobs, db.jobs.c.job_id == data["job_id"])

    def import_urls(self, urls):
        if self.settings.auth_enabled:
            return self._import_private(urls)
        if len(urls) > self.settings.import_max_urls:
            raise AppError("import_limit", "Too many URLs in one request", 422)
        items = []
        with self.db.write() as connection:
            for index, url in enumerate(urls):
                try:
                    video_id = normalize_url(url)
                except AppError as error:
                    items.append(dict(input_index=index, outcome="rejected", error_code=error.code))
                    continue
                video = row(connection, db.videos, db.videos.c.video_id == video_id)
                if video and video["status"] == "deleting":
                    items.append(
                        dict(
                            input_index=index,
                            outcome="rejected",
                            video_id=video_id,
                            error_code="video_deleting",
                        )
                    )
                    continue
                existing = video and video["status"] != "deleted"
                if existing:
                    job = (
                        connection.execute(
                            sa.select(db.jobs)
                            .where(
                                db.jobs.c.video_id == video_id,
                                db.jobs.c.kind == "import",
                                db.jobs.c.generation == video["generation"],
                            )
                            .order_by(db.jobs.c.created_at.desc())
                            .limit(1)
                        )
                        .mappings()
                        .first()
                    )
                else:
                    now = time.time()
                    generation = video["generation"] + 1 if video else 1
                    values = dict(
                        canonical_url=canonical_url(video_id),
                        status="queued",
                        generation=generation,
                        transcript_version=None,
                        indexed_version=None,
                        title=None,
                        channel_id=None,
                        channel_title=None,
                        thumbnail_url=None,
                        published_at=None,
                        updated_at=now,
                    )
                    if video:
                        connection.execute(
                            db.videos.update()
                            .where(db.videos.c.video_id == video_id)
                            .values(**values)
                        )
                    else:
                        connection.execute(
                            db.videos.insert().values(video_id=video_id, created_at=now, **values)
                        )
                    job = self._new_job(
                        connection,
                        "import",
                        {"original_url": canonical_url(video_id)},
                        video_id=video_id,
                        generation=generation,
                    )
                items.append(
                    dict(
                        input_index=index,
                        outcome="existing" if existing else "accepted",
                        video_id=video_id,
                        job_id=job["job_id"],
                    )
                )
        return items

    def _sources(self, connection, scope):
        scope = Scope.model_validate(scope)
        if scope.playlist_ids:
            raise AppError("unsupported_filter", "Playlist filtering is not implemented", 422)
        found = (
            connection.execute(
                sa.select(db.videos).where(db.videos.c.video_id.in_(scope.video_ids))
            )
            .mappings()
            .all()
        )
        by_id = {v["video_id"]: v for v in found}
        selected = []
        for video_id in scope.video_ids:
            self._require_video(connection, video_id)
            video = by_id.get(video_id)
            if not video or video["status"] in {"deleted", "deleting"}:
                raise AppError("video_not_found", "A selected video is unavailable", 404)
            if video["status"] != "ready" or not video["indexed_version"]:
                raise AppError("video_not_ready", "Every selected video must be ready", 409)
            if scope.channel_ids and video["channel_id"] not in scope.channel_ids:
                continue
            published = video["published_at"]
            if scope.date_from and (not published or published < scope.date_from.isoformat()):
                continue
            if scope.date_to and (not published or published > scope.date_to.isoformat()):
                continue
            selected.append(
                Source(
                    video_id=video_id,
                    generation=video["generation"],
                    transcript_version=video["indexed_version"],
                ).model_dump()
            )
        if not selected:
            raise AppError("empty_scope", "No selected ready videos match the filters", 422)
        return selected

    def _check_sources(self, connection, sources, owner=None):
        for source in sources:
            self._require_video(connection, source["video_id"], owner)
            video = row(connection, db.videos, db.videos.c.video_id == source["video_id"])
            if (
                not video
                or video["status"] != "ready"
                or any(
                    (
                        video["generation"] != source["generation"],
                        video["indexed_version"] != source["transcript_version"],
                    )
                )
            ):
                raise AppError("source_changed", "Selected sources changed; submit a new task", 409)

    def enqueue(self, kind, request, idempotency_key=None):
        moderation_event_id = None
        if kind == "chat":
            from .moderation import admit

            moderation_event_id = admit(self, request)
            request = {k: v for k, v in request.items() if k != "moderation_token"}
        request_hash = digest(request)
        from .auth import actor_id

        namespace = actor_id.get() if self.settings.auth_enabled else "legacy"
        key = digest([namespace, kind, idempotency_key]) if idempotency_key else None
        with self.db.write() as connection:
            owner = self._actor(connection)
            if key:
                previous = row(connection, db.jobs, db.jobs.c.idempotency_key == key)
                if previous:
                    if previous["request_hash"] != request_hash:
                        raise AppError(
                            "idempotency_conflict", "Key already used with different input", 409
                        )
                    self._private(connection, previous)
                    return previous
            sources = self._sources(connection, request["scope"])
            if kind == "analysis" and request["type"] == "compare" and len(sources) < 2:
                raise AppError("comparison_scope", "Comparison requires at least two videos", 422)
            payload = dict(request=request, sources=sources)
            if moderation_event_id:
                payload["moderation_event_id"] = moderation_event_id
            conversation_id = None
            if kind == "chat":
                conversation_id = request.get("conversation_id")
                if conversation_id:
                    if not row(
                        connection,
                        db.conversations,
                        db.conversations.c.conversation_id == conversation_id,
                    ):
                        raise AppError("conversation_not_found", "Conversation not found", 404)
                    self._private(
                        connection,
                        row(
                            connection,
                            db.conversations,
                            db.conversations.c.conversation_id == conversation_id,
                        ),
                    )
                    active = row(
                        connection,
                        db.jobs,
                        sa.and_(
                            db.jobs.c.conversation_id == conversation_id,
                            db.jobs.c.state.in_(ACTIVE),
                        ),
                    )
                    if active:
                        raise AppError(
                            "conversation_busy", "Wait for the pending conversation turn", 409
                        )
                else:
                    conversation_id = uid()
                    connection.execute(
                        db.conversations.insert().values(
                            conversation_id=conversation_id, created_at=time.time(), owner_id=owner
                        )
                    )
                history = (
                    connection.execute(
                        sa.select(db.messages)
                        .join(db.jobs, db.jobs.c.job_id == db.messages.c.job_id)
                        .where(
                            db.messages.c.conversation_id == conversation_id,
                            db.jobs.c.state == "completed",
                        )
                        .order_by(db.messages.c.created_at.desc())
                        .limit(40)
                    )
                    .mappings()
                    .all()
                )
                source_keys = {digest(s) for s in sources}
                payload["history"] = [
                    {"role": m["role"], "content": m["content"]}
                    for m in reversed(history)
                    if all(digest(s) in source_keys for s in m["scope"])
                ]
            job = self._new_job(
                connection,
                kind,
                payload,
                conversation_id=conversation_id,
                idempotency_key=key,
                request_hash=request_hash,
            )
            if kind == "chat":
                if moderation_event_id:
                    connection.execute(
                        db.review["events"]
                        .update()
                        .where(db.review["events"].c.event_id == moderation_event_id)
                        .values(job_id=job["job_id"])
                    )
                connection.execute(
                    db.messages.insert().values(
                        message_id=uid(),
                        conversation_id=conversation_id,
                        job_id=job["job_id"],
                        role="user",
                        content=request["question"],
                        scope=sources,
                        created_at=self._message_timestamp(connection, conversation_id),
                    )
                )
            return job

    def get_job(self, job_id, *, internal=False):
        with self.db.read() as connection:
            job = row(connection, db.jobs, db.jobs.c.job_id == job_id)
            if not internal:
                self._private(connection, job)
        if not job:
            raise AppError("job_not_found", "Job not found", 404)
        return job

    def check_evidence_bounds(self, evidence):
        with self.db.read() as connection:
            start, end = connection.execute(
                sa.select(
                    sa.func.min(db.segments.c.start_seconds),
                    sa.func.max(db.segments.c.start_seconds + db.segments.c.duration_seconds),
                ).where(
                    db.segments.c.video_id == evidence.video_id,
                    db.segments.c.version == evidence.transcript_version,
                )
            ).one()
        if start is None or evidence.start_seconds < start or evidence.end_seconds > end:
            raise AppError(
                "invalid_citation", "Evidence interval is outside the stored transcript", 502
            )

    def sources_available(self, job):
        with self.db.read() as connection:
            if self.settings.auth_enabled and job["kind"] in {"attach", "detach"}:
                video = row(connection, db.videos, db.videos.c.video_id == job["video_id"])
                return bool(
                    job["kind"] == "attach"
                    and video
                    and video["status"] == "ready"
                    and self._has_video(connection, job["owner_id"], job["video_id"])
                )
            try:
                self._check_sources(
                    connection, job["payload"].get("sources", []), owner=job["owner_id"]
                )
                return True
            except AppError:
                return False

    def chat_result(self, job):
        from .chat_review import feedback_for

        result = dict(job["result"])
        with self.db.read() as c:
            mid = c.scalar(
                sa.select(db.messages.c.message_id).where(
                    db.messages.c.job_id == job["job_id"], db.messages.c.role == "assistant"
                )
            )
            if mid:
                result["assistant_message_id"] = mid
                result["feedback"] = feedback_for(c, job["owner_id"], mid)
        return result

    def public_job(self, job):
        keys = (
            "job_id",
            "request_id",
            "kind",
            "video_id",
            "conversation_id",
            "state",
            "stage",
            "attempt_count",
            "max_attempts",
            "error_code",
            "retryable",
            "cancel_requested",
            "result",
        )
        result = {k: job[k] for k in keys}
        if job["kind"] == "chat" and job["result"]:
            result["result"] = self.chat_result(job)
        with self.db.read() as connection:
            wait = row(connection, db.v2["pauses"], db.v2["pauses"].c.job_id == job["job_id"])
        if wait:
            result["wait"] = wait["data"]
        result.update({k: iso(job[k]) for k in ("created_at", "updated_at", "available_at")})
        result["mode"] = self.settings.adapter_mode
        if job["kind"] not in {"import", "delete"}:
            result["sources_available"] = self.sources_available(job)
        if job["kind"] == "research":
            result["run_id"] = job["job_id"]
        return result

    def _video_failure(self, connection, job, status):
        if job["kind"] == "import":
            connection.execute(
                db.videos.update()
                .where(
                    db.videos.c.video_id == job["video_id"],
                    db.videos.c.generation == job["generation"],
                    db.videos.c.status.not_in(["deleting", "deleted"]),
                )
                .values(status=status, updated_at=time.time())
            )

    def claim(self, job_id=None):
        now = time.time()
        with self.db.write() as connection:
            expired = (
                connection.execute(
                    sa.select(db.jobs).where(
                        db.jobs.c.state == "running", db.jobs.c.lease_until <= now
                    )
                )
                .mappings()
                .all()
            )
            for job in expired:
                terminal = job["cancel_requested"] or job["attempt_count"] >= job["max_attempts"]
                state = (
                    ("cancelled" if job["cancel_requested"] else "failed") if terminal else "queued"
                )
                code = "cancelled" if job["cancel_requested"] else "worker_interrupted"
                connection.execute(
                    db.jobs.update()
                    .where(db.jobs.c.job_id == job["job_id"])
                    .values(
                        state=state,
                        stage=state if terminal else "queued",
                        lease_token=None,
                        lease_until=None,
                        error_code=code,
                        retryable=not job["cancel_requested"],
                        available_at=now,
                        updated_at=now,
                    )
                )
                self._video_failure(connection, job, "failed" if terminal else "queued")
            conditions = [db.jobs.c.state == "queued", db.jobs.c.available_at <= now]
            if job_id:
                conditions.append(db.jobs.c.job_id == job_id)
            if self.settings.auth_enabled:
                conditions.append(db.jobs.c.owner_id.is_not(None))
            candidates = (
                connection.execute(
                    sa.select(db.jobs).where(*conditions).order_by(db.jobs.c.created_at)
                )
                .mappings()
                .all()
            )
            for candidate in candidates:
                if self.settings.auth_enabled:
                    try:
                        self._check_job_authorization(connection, candidate)
                    except AppError:
                        connection.execute(
                            db.jobs.update()
                            .where(db.jobs.c.job_id == candidate["job_id"])
                            .values(state="cancelled", stage="cancelled", error_code="cancelled")
                        )
                        continue
                if candidate["kind"] == "attach":
                    video = row(
                        connection, db.videos, db.videos.c.video_id == candidate["video_id"]
                    )
                    if video["status"] not in {
                        "ready",
                        "failed",
                        "no_transcript",
                        "deleted",
                        "deleting",
                    }:
                        pending_import = connection.scalar(
                            sa.select(db.jobs.c.job_id)
                            .where(
                                db.jobs.c.video_id == candidate["video_id"],
                                db.jobs.c.kind == "import",
                                db.jobs.c.state.in_(ACTIVE),
                            )
                            .limit(1)
                        )
                        if pending_import:
                            continue
                if self.settings.auth_enabled and candidate["kind"] == "delete":
                    active_jobs = (
                        connection.execute(
                            sa.select(db.jobs).where(
                                db.jobs.c.state.in_(ACTIVE), db.jobs.c.job_id != candidate["job_id"]
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if any(
                        j["video_id"] == candidate["video_id"]
                        or any(
                            x["video_id"] == candidate["video_id"]
                            for x in j["payload"].get("sources", [])
                        )
                        for j in active_jobs
                    ):
                        continue
                if candidate["video_id"]:
                    busy = row(
                        connection,
                        db.jobs,
                        sa.and_(
                            db.jobs.c.video_id == candidate["video_id"],
                            db.jobs.c.state == "running",
                        ),
                    )
                    if busy:
                        continue
                token = uid()
                deadline = candidate["deadline_at"]
                if deadline is None:
                    duration = (
                        self.settings.agent_timeout_seconds
                        if candidate["kind"] == "research"
                        else self.settings.job_timeout_seconds
                    )
                    deadline = now + duration
                connection.execute(
                    db.jobs.update()
                    .where(db.jobs.c.job_id == candidate["job_id"])
                    .values(
                        state="running",
                        stage="running",
                        lease_token=token,
                        lease_until=now + self.settings.job_lease_seconds,
                        deadline_at=deadline,
                        attempt_count=candidate["attempt_count"] + 1,
                        updated_at=now,
                        error_code=None,
                        retryable=False,
                    )
                )
                connection.execute(
                    db.v2["pauses"].delete().where(db.v2["pauses"].c.job_id == candidate["job_id"])
                )
                return row(connection, db.jobs, db.jobs.c.job_id == candidate["job_id"])
        return None

    def _owned(self, connection, job_id, token, allow_cancel=False):
        job = row(connection, db.jobs, db.jobs.c.job_id == job_id)
        if not job or job["state"] != "running" or job["lease_token"] != token:
            raise LeaseLost
        if job["lease_until"] <= time.time():
            raise LeaseLost
        if job["cancel_requested"] and not allow_cancel:
            raise AppError("cancelled", "Task cancelled", 409)
        if not allow_cancel:
            if job["deadline_at"] is not None and job["deadline_at"] <= time.time():
                raise AppError("task_timeout", "Task exceeded its deadline", 504)
            self._check_job_authorization(connection, job)
            if job["kind"] in {"import", "delete", "attach", "enrich"}:
                video = row(connection, db.videos, db.videos.c.video_id == job["video_id"])
                if (
                    not video
                    or video["generation"] != job["generation"]
                    or (job["kind"] == "delete" and video["status"] != "deleting")
                    or (job["kind"] != "delete" and video["status"] in {"deleting", "deleted"})
                ):
                    raise AppError("cancelled", "Source lifecycle changed", 409)
        return job

    def check_execution(self, job_id, token):
        with self.db.read() as connection:
            job = self._owned(connection, job_id, token)
            if job["kind"] in {"import", "delete", "attach", "enrich"}:
                video = row(connection, db.videos, db.videos.c.video_id == job["video_id"])
                expected = "deleting" if job["kind"] == "delete" else None
                if (
                    video["generation"] != job["generation"]
                    or (expected and video["status"] != expected)
                    or (not expected and video["status"] in {"deleting", "deleted"})
                ):
                    raise AppError("cancelled", "Video is being deleted", 409)
            else:
                self._check_sources(connection, job["payload"]["sources"], owner=job["owner_id"])
            return job

    def heartbeat(self, job_id, token):
        with self.db.write() as connection:
            self._owned(connection, job_id, token)
            connection.execute(
                db.jobs.update()
                .where(db.jobs.c.job_id == job_id)
                .values(
                    lease_until=time.time() + self.settings.job_lease_seconds,
                    updated_at=time.time(),
                )
            )

    def stage(self, job_id, token, stage):
        with self.db.write() as connection:
            job = self._owned(connection, job_id, token)
            connection.execute(
                db.jobs.update()
                .where(db.jobs.c.job_id == job_id)
                .values(stage=stage, updated_at=time.time())
            )
            if job["kind"] == "import":
                connection.execute(
                    db.videos.update()
                    .where(
                        db.videos.c.video_id == job["video_id"],
                        db.videos.c.generation == job["generation"],
                        db.videos.c.status.not_in(["deleting", "deleted"]),
                    )
                    .values(status=stage, updated_at=time.time())
                )

    def save_transcript(self, job_id, token, transcript: TranscriptResult):
        version = digest(
            transcript.model_dump(
                mode="json", include={"video_id", "language", "source", "segments"}
            )
        )
        with self.db.write() as connection:
            job = self._owned(connection, job_id, token)
            if transcript.video_id != job["video_id"]:
                raise AppError("adapter_invalid_output", "Transcript video does not match job", 502)
            video = row(connection, db.videos, db.videos.c.video_id == job["video_id"])
            if video["status"] in {"deleting", "deleted"}:
                raise AppError("cancelled", "Video is being deleted", 409)
            if not row(
                connection,
                db.transcripts,
                sa.and_(
                    db.transcripts.c.video_id == transcript.video_id,
                    db.transcripts.c.version == version,
                ),
            ):
                connection.execute(
                    db.transcripts.insert().values(
                        video_id=transcript.video_id,
                        version=version,
                        language=transcript.language,
                        source=transcript.source,
                        created_at=time.time(),
                    )
                )
                connection.execute(
                    db.segments.insert(),
                    [
                        dict(
                            video_id=transcript.video_id,
                            version=version,
                            position=i,
                            **segment.model_dump(),
                        )
                        for i, segment in enumerate(transcript.segments)
                    ],
                )
            values = transcript.model_dump(
                mode="json", exclude={"segments", "video_id", "language", "source"}
            )
            connection.execute(
                db.videos.update()
                .where(db.videos.c.video_id == transcript.video_id)
                .values(**values, transcript_version=version, updated_at=time.time())
            )
        return Source(
            video_id=transcript.video_id, generation=job["generation"], transcript_version=version
        )

    def fail(self, job_id, token, error, *, deadline_exhausted=False):
        with self.db.write() as connection:
            job = self._owned(connection, job_id, token, allow_cancel=True)
            cancelled = job["cancel_requested"] or error.code == "cancelled"
            # Avoid consuming all durable attempts in a few seconds during a
            # provider outage or quota window. Retain the original job deadline.
            provider_floor = {
                "generation_provider_busy": 15,
                "generation_rate_limited": 60,
                "provider_unavailable": 15,
                "provider_rate_limited": 60,
                "provider_timeout": 5,
                "quota_wait": 60,
            }.get(error.code, 0)
            base_delay = max(self.settings.job_retry_base_seconds, provider_floor)
            delay = min(300, base_delay * 2 ** (job["attempt_count"] - 1))
            if error.code.startswith("provider_") or error.code == "quota_wait":
                delay += random.uniform(0, min(10, delay * 0.2))
            if error.retry_after_seconds is not None:
                delay = max(delay, error.retry_after_seconds)
            retry = (
                not cancelled
                and not deadline_exhausted
                and error.retryable
                and job["attempt_count"] < job["max_attempts"]
                and time.time() + delay < job["deadline_at"]
            )
            missing = not cancelled and error.code == "no_transcript" and job["kind"] == "import"
            paused = not cancelled and job["kind"] == "enrich" and error.pause
            state = (
                "cancelled"
                if cancelled
                else "paused"
                if paused
                else "queued"
                if retry
                else "completed"
                if missing
                else "failed"
            )
            visual_pending = False
            if missing:
                media = db.v2["media_states"]
                visual_pending = bool(
                    connection.scalar(
                        sa.select(media.c.video_id).where(
                            media.c.video_id == job["video_id"],
                            media.c.generation == job["generation"],
                            media.c.state.in_(["pending", "processing", "ready"]),
                        )
                    )
                )
            stage = "visual_pending" if visual_pending else "no_transcript" if missing else state
            if error.retry_after_seconds is not None or paused:
                from sqlalchemy.dialects.sqlite import insert

                waits = db.v2["pauses"]
                known = error.retry_time_source == "provider"
                data = {
                    "reason": error.code,
                    "time_source": "provider" if known else "estimate",
                    "retry_at" if known else "estimated_retry_at": iso(
                        time.time() + (error.retry_after_seconds if known else delay)
                    ),
                }
                if retry and not paused:
                    data["scheduled_retry_at"] = iso(time.time() + delay)
                connection.execute(
                    insert(waits)
                    .values(job_id=job_id, data=data)
                    .on_conflict_do_update(index_elements=[waits.c.job_id], set_={"data": data})
                )
            connection.execute(
                db.jobs.update()
                .where(db.jobs.c.job_id == job_id)
                .values(
                    state=state,
                    stage=stage,
                    error_code="cancelled" if cancelled else error.code,
                    retryable=bool((error.retryable or paused) and not cancelled),
                    lease_token=None,
                    lease_until=None,
                    available_at=time.time() + delay,
                    updated_at=time.time(),
                )
            )
            self._video_failure(
                connection,
                job,
                "visual_pending"
                if visual_pending
                else "no_transcript"
                if missing
                else "queued"
                if retry
                else "failed",
            )
            if job["kind"] == "enrich":
                table = db.v2["media_states"]
                connection.execute(
                    table.update()
                    .where(
                        table.c.video_id == job["video_id"], table.c.generation == job["generation"]
                    )
                    .values(
                        state="paused" if paused else "pending" if retry else "failed",
                        error_code=error.code,
                        updated_at=time.time(),
                    )
                )

    def finish(self, job_id, token, result=None, state="completed"):
        with self.db.write() as connection:
            job = self._owned(connection, job_id, token)
            kind = job["kind"]
            if kind not in {"import", "delete", "attach", "enrich"}:
                self._check_sources(connection, job["payload"]["sources"], owner=job["owner_id"])
            if kind in {"chat", "analysis", "artifact", "research"} and result:
                from .schemas import Citation
                from .video_evidence import verify_video_citation

                for value in result.get("citations", []):
                    citation = Citation.model_validate(value)
                    if citation.kind == "video":
                        verify_video_citation(self, connection, job, citation)
            if kind == "attach":
                video = row(connection, db.videos, db.videos.c.video_id == job["video_id"])
                if video["status"] != "ready":
                    raise AppError(
                        "source_unavailable", "Shared source import did not complete", 409
                    )
            if kind == "import":
                video = row(connection, db.videos, db.videos.c.video_id == job["video_id"])
                if video["status"] in {"deleting", "deleted"}:
                    raise AppError("cancelled", "Video is being deleted", 409)
                connection.execute(
                    db.videos.update()
                    .where(db.videos.c.video_id == job["video_id"])
                    .values(
                        status="ready",
                        indexed_version=video["transcript_version"],
                        updated_at=time.time(),
                    )
                )
            elif kind == "delete":
                connection.execute(
                    db.segments.delete().where(db.segments.c.video_id == job["video_id"])
                )
                connection.execute(
                    db.transcripts.delete().where(db.transcripts.c.video_id == job["video_id"])
                )
                connection.execute(
                    db.videos.update()
                    .where(db.videos.c.video_id == job["video_id"])
                    .values(
                        status="deleted",
                        title=None,
                        channel_id=None,
                        channel_title=None,
                        thumbnail_url=None,
                        published_at=None,
                        transcript_version=None,
                        indexed_version=None,
                        updated_at=time.time(),
                    )
                )
            elif kind == "chat":
                from .moderation import inspect_output

                message_id = uid()
                result = inspect_output(self, connection, job, result, None)
                connection.execute(
                    db.messages.insert().values(
                        message_id=message_id,
                        conversation_id=job["conversation_id"],
                        job_id=job_id,
                        role="assistant",
                        content=result["answer"],
                        scope=job["payload"]["sources"],
                        created_at=self._message_timestamp(connection, job["conversation_id"]),
                    )
                )
                for citation in result["citations"]:
                    connection.execute(
                        db.citations.insert().values(
                            message_id=message_id,
                            citation_id=citation["citation_id"],
                            video_id=citation["video_id"],
                            data=citation,
                        )
                    )
                for table in (db.review["events"], db.review["cases"]):
                    if "job_id" in table.c:
                        condition = table.c.job_id == job_id
                    else:
                        condition = table.c.event_id.in_(
                            sa.select(db.review["events"].c.event_id).where(
                                db.review["events"].c.job_id == job_id
                            )
                        )
                    connection.execute(
                        table.update()
                        .where(condition, table.c.message_id.is_(None))
                        .values(message_id=message_id)
                    )
                result = dict(
                    result,
                    conversation_id=job["conversation_id"],
                    job_id=job_id,
                    assistant_message_id=message_id,
                    mode=self.settings.adapter_mode,
                )
            if kind in {"artifact", "research"}:
                outputs = [result] if kind == "artifact" else result["artifacts"]
                artifact_ids = []
                for output in outputs:
                    artifact_id = uid()
                    artifact_ids.append(artifact_id)
                    connection.execute(
                        db.artifacts.insert().values(
                            artifact_id=artifact_id,
                            owner_id=job["owner_id"],
                            job_id=job_id,
                            scope=job["payload"]["sources"],
                            data=output,
                            created_at=time.time(),
                        )
                    )
                result = dict(result, artifact_ids=artifact_ids)
            connection.execute(
                db.jobs.update()
                .where(db.jobs.c.job_id == job_id)
                .values(
                    state=state,
                    stage="ready" if kind in {"import", "attach"} else state,
                    result=result,
                    error_code=None,
                    retryable=False,
                    lease_token=None,
                    lease_until=None,
                    updated_at=time.time(),
                )
            )

    def delete_video(self, video_id):
        if self.settings.auth_enabled:
            return self._delete_private(video_id)
        with self.db.write() as connection:
            video = row(connection, db.videos, db.videos.c.video_id == video_id)
            if not video or video["status"] == "deleted":
                raise AppError("video_not_found", "Video not found", 404)
            if video["status"] == "deleting":
                return dict(
                    connection.execute(
                        sa.select(db.jobs)
                        .where(db.jobs.c.video_id == video_id, db.jobs.c.kind == "delete")
                        .order_by(db.jobs.c.created_at.desc())
                        .limit(1)
                    )
                    .mappings()
                    .one()
                )
            connection.execute(
                db.videos.update()
                .where(db.videos.c.video_id == video_id)
                .values(status="deleting", updated_at=time.time())
            )
            active = (
                connection.execute(sa.select(db.jobs).where(db.jobs.c.state.in_(ACTIVE)))
                .mappings()
                .all()
            )
            for job in active:
                uses = job["video_id"] == video_id or any(
                    s["video_id"] == video_id for s in job["payload"].get("sources", [])
                )
                if uses:
                    values = dict(cancel_requested=True, updated_at=time.time())
                    if job["state"] == "queued":
                        values.update(state="cancelled", stage="cancelled", error_code="cancelled")
                    connection.execute(
                        db.jobs.update().where(db.jobs.c.job_id == job["job_id"]).values(**values)
                    )
            return self._new_job(
                connection, "delete", {}, video_id=video_id, generation=video["generation"]
            )

    def cancel(self, job_id):
        with self.db.write() as connection:
            job = row(connection, db.jobs, db.jobs.c.job_id == job_id)
            self._private(connection, job)
            if not job:
                raise AppError("job_not_found", "Job not found", 404)
            if self.settings.auth_enabled and job["kind"] == "import":
                count = connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(db.user_videos)
                    .where(db.user_videos.c.video_id == job["video_id"])
                )
                if count > 1:
                    raise AppError(
                        "shared_import_required", "Remove from your library instead", 409
                    )
            if job["kind"] == "delete":
                raise AppError("deletion_committed", "Deletion cannot be cancelled", 409)
            if job["state"] in ACTIVE or job["state"] == "paused":
                values = dict(cancel_requested=True, updated_at=time.time())
                if job["state"] in {"queued", "paused"}:
                    values.update(state="cancelled", stage="cancelled", error_code="cancelled")
                    self._video_failure(connection, job, "failed")
                connection.execute(
                    db.jobs.update().where(db.jobs.c.job_id == job_id).values(**values)
                )
        return self.get_job(job_id)

    def retry(self, job_id):
        old = self.get_job(job_id)
        if old["kind"] == "enrich":
            from .media import MediaStore

            return MediaStore(self).enqueue(old["video_id"], resume_job=job_id)
        if self.settings.auth_enabled:
            old = self.get_job(job_id)
            if old["kind"] == "attach" and old["state"] == "failed":
                imported = self._import_private([canonical_url(old["video_id"])])
                if not imported[0].get("job_id"):
                    raise AppError("retry_not_allowed", "Source is not available", 409)
                return self.get_job(imported[0]["job_id"])
        with self.db.write() as connection:
            job = row(connection, db.jobs, db.jobs.c.job_id == job_id)
            self._private(connection, job)
            if not job:
                raise AppError("job_not_found", "Job not found", 404)
            if job["kind"] not in {"import", "delete"} or job["state"] != "failed":
                raise AppError(
                    "retry_not_allowed", "Only failed import/deletion jobs can be retried", 409
                )
            if not job["retryable"]:
                raise AppError("retry_not_allowed", "This error is not retryable", 409)
            video = row(connection, db.videos, db.videos.c.video_id == job["video_id"])
            if (
                video["generation"] != job["generation"]
                or (job["kind"] == "import" and video["status"] in {"deleting", "deleted", "ready"})
                or (job["kind"] == "delete" and video["status"] != "deleting")
            ):
                raise AppError("retry_not_allowed", "Video lifecycle has changed", 409)
            active = row(
                connection,
                db.jobs,
                sa.and_(db.jobs.c.video_id == job["video_id"], db.jobs.c.state.in_(ACTIVE)),
            )
            if active:
                if self.settings.auth_enabled and active["owner_id"] != self._actor(connection):
                    return self._new_job(
                        connection,
                        "attach",
                        {},
                        video_id=job["video_id"],
                        generation=job["generation"],
                    )
                return active
            if job["kind"] == "import":
                connection.execute(
                    db.videos.update()
                    .where(db.videos.c.video_id == job["video_id"])
                    .values(status="queued", updated_at=time.time())
                )
            return self._new_job(
                connection,
                job["kind"],
                job["payload"],
                video_id=job["video_id"],
                generation=job["generation"],
            )

    def add_event(self, job_id, token, data):
        with self.db.write() as connection:
            self._owned(connection, job_id, token)
            count = connection.scalar(
                sa.select(sa.func.count())
                .select_from(db.events)
                .where(db.events.c.job_id == job_id)
            )
            if (
                count >= self.settings.agent_max_steps * 3
                or data["step"] > self.settings.agent_max_steps
            ):
                raise AppError("agent_budget_exceeded", "Agent exceeded its event/step budget", 502)
            connection.execute(
                db.events.insert().values(job_id=job_id, data=data, created_at=time.time())
            )

    def list_events(self, job_id, after=0, limit=100):
        self.get_job(job_id)
        with self.db.read() as connection:
            return [
                dict(event_id=e.event_id, **e.data, timestamp=iso(e.created_at))
                for e in connection.execute(
                    sa.select(db.events)
                    .where(db.events.c.job_id == job_id, db.events.c.event_id > after)
                    .order_by(db.events.c.event_id)
                    .limit(limit)
                )
            ]

    def list_videos(self, limit, offset, channel_id=None, date_from=None, date_to=None):
        conditions = [db.videos.c.status.not_in(["deleted", "deleting"])]
        if self.settings.auth_enabled:
            from .auth import actor_id

            conditions.append(
                db.videos.c.video_id.in_(
                    sa.select(db.user_videos.c.video_id).where(
                        db.user_videos.c.user_id == actor_id.get()
                    )
                )
            )
        if channel_id:
            conditions.append(db.videos.c.channel_id == channel_id)
        if date_from:
            conditions.append(db.videos.c.published_at >= date_from.isoformat())
        if date_to:
            conditions.append(db.videos.c.published_at <= date_to.isoformat())
        with self.db.read() as connection:
            total = connection.scalar(
                sa.select(sa.func.count()).select_from(db.videos).where(*conditions)
            )
            items = [
                dict(v)
                for v in connection.execute(
                    sa.select(db.videos)
                    .where(*conditions)
                    .order_by(db.videos.c.created_at, db.videos.c.video_id)
                    .offset(offset)
                    .limit(limit)
                ).mappings()
            ]
        for item in items:
            item["created_at"], item["updated_at"] = (
                iso(item["created_at"]),
                iso(item["updated_at"]),
            )
        return dict(
            items=items, total=total, limit=limit, offset=offset, mode=self.settings.adapter_mode
        )

    def transcript(self, video_id, limit, offset):
        with self.db.read() as connection:
            self._require_video(connection, video_id)
            video = row(connection, db.videos, db.videos.c.video_id == video_id)
            if not video or video["status"] in {"deleting", "deleted"}:
                raise AppError("video_not_found", "Video not found", 404)
            if not video["transcript_version"]:
                raise AppError("transcript_unavailable", "Transcript is not available", 409)
            version = video["transcript_version"]
            transcript = row(
                connection,
                db.transcripts,
                sa.and_(db.transcripts.c.video_id == video_id, db.transcripts.c.version == version),
            )
            condition = sa.and_(
                db.segments.c.video_id == video_id, db.segments.c.version == version
            )
            total = connection.scalar(
                sa.select(sa.func.count()).select_from(db.segments).where(condition)
            )
            items = [
                dict(s)
                for s in connection.execute(
                    sa.select(db.segments)
                    .where(condition)
                    .order_by(db.segments.c.position)
                    .limit(limit)
                    .offset(offset)
                ).mappings()
            ]
        for item in items:
            item["transcript_version"] = item.pop("version")
            item["language"] = transcript["language"]
        return dict(
            video_id=video_id,
            transcript_version=version,
            language=transcript["language"],
            source=transcript["source"],
            segments=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    def conversations(self, limit, offset, query=""):
        with self.db.read() as connection:
            owner = self._actor(connection)
            # The first question supplies a deterministic title without a provider call.
            first_question = (
                sa.select(db.messages.c.content)
                .where(
                    db.messages.c.conversation_id == db.conversations.c.conversation_id,
                    db.messages.c.role == "user",
                )
                .order_by(db.messages.c.created_at, db.messages.c.message_id)
                .limit(1)
                .scalar_subquery()
            )
            updated = (
                sa.select(sa.func.max(db.messages.c.created_at))
                .where(db.messages.c.conversation_id == db.conversations.c.conversation_id)
                .scalar_subquery()
            )
            condition = db.conversations.c.owner_id == owner
            title = sa.func.substr(first_question, 1, 160)
            if query.strip():
                condition = sa.and_(condition, title.contains(query.strip(), autoescape=True))
            total = connection.scalar(
                sa.select(sa.func.count()).select_from(db.conversations).where(condition)
            )
            records = connection.execute(
                sa.select(
                    db.conversations,
                    title.label("title"),
                    sa.func.coalesce(updated, db.conversations.c.created_at).label("updated"),
                )
                .where(condition)
                .order_by(sa.desc("updated"), db.conversations.c.conversation_id)
                .limit(limit)
                .offset(offset)
            ).mappings()
            items = []
            for record in records:
                message_filter = db.messages.c.conversation_id == record["conversation_id"]
                message_count = connection.scalar(
                    sa.select(sa.func.count()).select_from(db.messages).where(message_filter)
                )
                last_scope = (
                    connection.scalar(
                        sa.select(db.messages.c.scope)
                        .where(message_filter)
                        .order_by(db.messages.c.created_at.desc(), db.messages.c.message_id.desc())
                        .limit(1)
                    )
                    or []
                )
                items.append(
                    dict(
                        conversation_id=record["conversation_id"],
                        title=record["title"] or "บทสนทนาใหม่",
                        created_at=iso(record["created_at"]),
                        updated_at=iso(record["updated"]),
                        message_count=message_count,
                        video_ids=list(dict.fromkeys(s["video_id"] for s in last_scope)),
                    )
                )
        return dict(items=items, total=total, limit=limit, offset=offset)

    def conversation(self, conversation_id, limit, offset):
        with self.db.read() as connection:
            self._private(
                connection,
                row(
                    connection,
                    db.conversations,
                    db.conversations.c.conversation_id == conversation_id,
                ),
            )
            if not row(
                connection, db.conversations, db.conversations.c.conversation_id == conversation_id
            ):
                raise AppError("conversation_not_found", "Conversation not found", 404)
            condition = db.messages.c.conversation_id == conversation_id
            total = connection.scalar(
                sa.select(sa.func.count()).select_from(db.messages).where(condition)
            )
            items = []
            for message in connection.execute(
                sa.select(db.messages)
                .where(condition)
                .order_by(db.messages.c.created_at, db.messages.c.message_id)
                .limit(limit)
                .offset(offset)
            ).mappings():
                item = dict(message)
                item["created_at"] = iso(item["created_at"])
                item["citations"] = []
                for citation in connection.execute(
                    sa.select(db.citations).where(db.citations.c.message_id == item["message_id"])
                ).mappings():
                    video = row(connection, db.videos, db.videos.c.video_id == citation["video_id"])
                    available = bool(
                        (
                            not self.settings.auth_enabled
                            or self._has_video(
                                connection, self._actor(connection), citation["video_id"]
                            )
                        )
                        and video
                        and video["status"] == "ready"
                        and any(
                            s["video_id"] == video["video_id"]
                            and s["generation"] == video["generation"]
                            and s["transcript_version"] == video["indexed_version"]
                            for s in item["scope"]
                        )
                    )
                    item["citations"].append(dict(citation["data"], source_available=available))
                item["state"] = row(connection, db.jobs, db.jobs.c.job_id == item["job_id"])[
                    "state"
                ]
                if item["role"] == "assistant":
                    from .chat_review import feedback_for

                    job = row(connection, db.jobs, db.jobs.c.job_id == item["job_id"])
                    item["visibility"] = (job["result"] or {}).get("visibility", "published")
                    item["feedback"] = feedback_for(connection, job["owner_id"], item["message_id"])
                items.append(item)
            latest_job = connection.execute(
                sa.select(db.jobs.c.payload)
                .where(db.jobs.c.conversation_id == conversation_id)
                .order_by(db.jobs.c.created_at.desc(), db.jobs.c.job_id.desc())
                .limit(1)
            ).scalar()
            scope = latest_job.get("request", {}).get("scope") if latest_job else None
        return dict(
            conversation_id=conversation_id,
            messages=items,
            total=total,
            limit=limit,
            offset=offset,
            scope=scope,
        )

    def artifact(self, artifact_id):
        with self.db.read() as connection:
            artifact = row(connection, db.artifacts, db.artifacts.c.artifact_id == artifact_id)
            self._private(connection, artifact)
            if not artifact:
                raise AppError("artifact_not_found", "Artifact not found", 404)
            try:
                self._check_sources(connection, artifact["scope"])
                available = True
            except AppError:
                available = False
        return dict(
            artifact_id=artifact_id,
            job_id=artifact["job_id"],
            scope=artifact["scope"],
            **artifact["data"],
            sources_available=available,
            created_at=iso(artifact["created_at"]),
            mode=self.settings.adapter_mode,
        )
