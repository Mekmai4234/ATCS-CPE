"""Contract simulation only. Not a session verifier or production membership store."""

from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

from youtube_backend.errors import AppError

from youtube_ingestion.members import CONTRACT_VERSION, REQUIRED_GUARANTEES, SourceGrant


class MemberBackendDouble:
    contract_version = CONTRACT_VERSION
    guarantees = REQUIRED_GUARANTEES

    def __init__(self):
        self.lock = RLock()
        self.a, self.b, self.admin = object(), object(), object()
        self.sessions = {self.a: "member-a", self.b: "member-b", self.admin: "admin"}
        self.refs, self.sources, self.jobs, self.member_jobs = {}, {}, {}, {}
        self.source_jobs = 0
        self.commands = []

    def require_member(self, context):
        if not any(context is session for session in self.sessions):
            raise AppError("authentication_required", "Sign in first", 401)

    def execute_member(self, context, operation, payload, limits):
        with self.lock:
            self.require_member(context)
            member = self.sessions[context]
            self.commands.append((member, operation, dict(payload), dict(limits)))
            if operation == "add":
                result = []
                for video_id in payload["video_ids"]:
                    existing = (member, video_id) in self.member_jobs and member in self.refs.get(
                        video_id, set()
                    )
                    pending = sum(
                        j["state"] in {"queued", "running"}
                        for (m, _), job_id in self.member_jobs.items()
                        if m == member
                        for j in [self.jobs[job_id]]
                    )
                    source = self.sources.get(video_id)
                    if (
                        not existing
                        and pending >= limits["pending_import_limit"]
                        and not (source and source["ready"])
                    ):
                        result.append(
                            dict(
                                video_id=video_id,
                                outcome="rejected",
                                status="rejected",
                                error_code="member_pending_limit",
                            )
                        )
                        continue
                    if source is None:
                        source = self.sources[video_id] = dict(
                            ready=False, active=True, generation=1
                        )
                        self.source_jobs += 1
                    self.refs.setdefault(video_id, set()).add(member)
                    if not existing:
                        job_id = str(uuid4())
                        self.member_jobs[member, video_id] = job_id
                        self.jobs[job_id] = dict(
                            job_id=job_id,
                            member=member,
                            video_id=video_id,
                            state="completed" if source["ready"] else "queued",
                            stage="ready" if source["ready"] else "queued",
                            retryable=False,
                            error_code=None,
                        )
                    job = self.jobs[self.member_jobs[member, video_id]]
                    result.append(
                        dict(
                            video_id=video_id,
                            job_id=job["job_id"],
                            outcome="existing" if existing else "added",
                            status="ready" if source["ready"] else "importing",
                        )
                    )
                return result
            if operation in {"job", "retry", "cancel"}:
                job = self.jobs.get(payload["job_id"])
                if not job or job["member"] != member:
                    raise AppError("job_not_found", "Job not found", 404)
                if operation == "cancel" and job["state"] in {"queued", "running"}:
                    job.update(state="cancelled", stage="cancelled")
                    # Only this member's job interest changes; shared work stays active.
                if operation == "retry":
                    if job["state"] != "failed" or not job["retryable"]:
                        raise AppError("retry_not_allowed", "Retry not allowed", 409)
                    job.update(state="queued", stage="queued", error_code=None, retryable=False)
                return {key: value for key, value in job.items() if key != "member"}
            video_id = payload["video_id"]
            if member not in self.refs.get(video_id, set()):
                raise AppError("video_not_found", "Video not found", 404)
            if operation == "remove":
                self.refs[video_id].remove(member)
                return dict(
                    video_id=video_id,
                    removed=True,
                    gc_scheduled=not self.refs[video_id] and not self.sources[video_id]["active"],
                )
            if operation == "transcript":
                if not self.sources[video_id]["ready"]:
                    raise AppError("video_not_ready", "Video not ready", 409)
                segments = [
                    dict(
                        segment_id="s1",
                        text="Shared public caption",
                        start_seconds=0,
                        duration_seconds=2,
                        video_id=video_id,
                        transcript_version="v1",
                        language="th",
                        position=0,
                    )
                ]
                offset, limit = payload["offset"], payload["limit"]
                return dict(
                    video_id=video_id,
                    transcript_version="v1",
                    language="th",
                    source="fixture",
                    segments=segments[offset : offset + limit],
                    total=1,
                    limit=limit,
                    offset=offset,
                )
            raise AssertionError(operation)

    def finish(self, video_id):
        with self.lock:
            self.sources[video_id].update(ready=True, active=False)
            for job in self.jobs.values():
                if job["video_id"] == video_id and job["state"] != "cancelled":
                    job.update(state="completed", stage="ready")

    def authorize_source(self, context, command):
        def check():
            if command.action == "read":
                self.require_member(context)
                member = self.sessions[context]
                if any(
                    member not in self.refs.get(s.video_id, set())
                    or s.transcript_version != "v1"
                    or s.generation != self.sources[s.video_id]["generation"]
                    for s in command.sources
                ):
                    raise AppError("source_unavailable", "Source unavailable", 404)
            elif context is not self:
                raise AppError("shared_execution_required", "Shared worker claim required", 403)
            elif command.action == "gc":
                source = self.sources[command.video_id]
                if (
                    self.refs[command.video_id]
                    or source["active"]
                    or command.generation != source["generation"]
                ):
                    raise AppError("source_in_use", "Source is in use", 409)

            else:
                source = self.sources.get(command.video_id)
                if not source or not source["active"] or not self.refs.get(command.video_id):
                    raise AppError("source_unavailable", "Source unavailable", 409)
                if command.generation is not None and command.generation != source["generation"]:
                    raise AppError("source_changed", "Source generation changed", 409)

        check()
        return SourceGrant(command, SimpleNamespace(check=check, remaining_seconds=30))
