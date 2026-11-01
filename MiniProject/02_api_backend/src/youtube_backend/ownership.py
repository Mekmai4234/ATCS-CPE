"""Private libraries over shared sources; all mutations use the backend writer lock."""

import time

import sqlalchemy as sa

from . import database as db
from .auth import actor_id
from .errors import AppError
from .urls import canonical_url, normalize_url


class Ownership:
    def _actor(self, connection):
        if not self.settings.auth_enabled:
            return None
        user_id = actor_id.get()
        active = (
            connection.scalar(
                sa.select(db.users.c.user_id).where(
                    db.users.c.user_id == user_id, db.users.c.status == "active"
                )
            )
            if user_id
            else None
        )
        if not active:
            raise AppError(
                "authentication_required", "An active authenticated account is required", 401
            )
        return user_id

    def _private(self, connection, record):
        if self.settings.auth_enabled and (
            not record or record["owner_id"] != self._actor(connection)
        ):
            raise AppError("not_found", "Resource not found", 404)

    def _has_video(self, connection, owner, video_id):
        return bool(
            connection.scalar(
                sa.select(db.user_videos.c.video_id).where(
                    db.user_videos.c.user_id == owner, db.user_videos.c.video_id == video_id
                )
            )
        )

    def _require_video(self, connection, video_id, owner=None):
        if self.settings.auth_enabled and not self._has_video(
            connection, owner or self._actor(connection), video_id
        ):
            raise AppError("video_not_found", "Video not found", 404)

    def _check_job_authorization(self, connection, job):
        if not self.settings.auth_enabled:
            return
        owner = job["owner_id"]
        if not owner or (
            job["kind"] != "delete"
            and not connection.scalar(
                sa.select(db.users.c.user_id).where(
                    db.users.c.user_id == owner, db.users.c.status == "active"
                )
            )
        ):
            raise AppError("cancelled", "Account no longer authorizes this execution", 409)
        if job["kind"] == "delete":
            if connection.scalar(
                sa.select(sa.func.count())
                .select_from(db.user_videos)
                .where(db.user_videos.c.video_id == job["video_id"])
            ):
                raise AppError("source_in_use", "Source still belongs to a library", 409)
        elif job["kind"] == "import":
            # Shared ingestion may finish for other subscribers after its creator detaches.
            if not connection.scalar(
                sa.select(db.user_videos.c.video_id)
                .join(db.users)
                .where(db.user_videos.c.video_id == job["video_id"])
                .where(db.users.c.status == "active")
                .limit(1)
            ):
                raise AppError("cancelled", "No library authorizes this import", 409)
        elif job["kind"] == "reindex":
            if (
                not self.settings.trial_reindex_enabled
                or self.settings.app_env not in {"test", "development"}
                or connection.scalar(sa.select(db.users.c.role).where(db.users.c.user_id == owner))
                != "admin"
            ):
                raise AppError("cancelled", "Trial administrator no longer authorizes reindex", 409)
            self._check_sources(connection, job["payload"].get("sources", []), owner=owner)
        elif job["kind"] in {"attach", "enrich"}:
            self._require_video(connection, job["video_id"], owner)
        else:
            self._check_sources(connection, job["payload"].get("sources", []), owner=owner)

    def _import_private(self, urls):
        from .repository import row

        if len(urls) > self.settings.import_max_urls:
            raise AppError("import_limit", "Too many URLs", 422)
        items = []
        with self.db.write() as c:
            owner = self._actor(c)
            for position, url in enumerate(urls):
                try:
                    video_id = normalize_url(url)
                except AppError as error:
                    items.append(
                        dict(input_index=position, outcome="rejected", error_code=error.code)
                    )
                    continue
                video = row(c, db.videos, db.videos.c.video_id == video_id)
                if c.scalar(
                    sa.select(db.legacy_sources.c.video_id).where(
                        db.legacy_sources.c.video_id == video_id
                    )
                ) or (
                    video
                    and video["status"] not in {"deleted", "deleting"}
                    and not c.scalar(
                        sa.select(db.user_videos.c.video_id)
                        .where(db.user_videos.c.video_id == video_id)
                        .limit(1)
                    )
                ):
                    items.append(
                        dict(
                            input_index=position,
                            outcome="rejected",
                            error_code="source_unavailable",
                        )
                    )
                    continue
                if video and video["status"] == "deleting":
                    items.append(
                        dict(
                            input_index=position,
                            outcome="rejected",
                            video_id=video_id,
                            error_code="video_deleting",
                        )
                    )
                    continue
                member = self._has_video(c, owner, video_id)
                previous = (
                    c.execute(
                        sa.select(db.jobs)
                        .where(
                            db.jobs.c.owner_id == owner,
                            db.jobs.c.video_id == video_id,
                            db.jobs.c.kind.in_(["import", "attach"]),
                        )
                        .order_by(db.jobs.c.created_at.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if (
                    member
                    and previous
                    and (previous["state"] in {"queued", "running"} or video["status"] == "ready")
                ):
                    job = previous
                else:
                    now = time.time()
                    if not video or video["status"] == "deleted":
                        generation = video["generation"] + 1 if video else 1
                        values = dict(
                            status="queued",
                            generation=generation,
                            canonical_url=canonical_url(video_id),
                            updated_at=now,
                            transcript_version=None,
                            indexed_version=None,
                        )
                        if video:
                            c.execute(
                                db.videos.update()
                                .where(db.videos.c.video_id == video_id)
                                .values(**values)
                            )
                        else:
                            c.execute(
                                db.videos.insert().values(
                                    video_id=video_id, created_at=now, **values
                                )
                            )
                        video = row(c, db.videos, db.videos.c.video_id == video_id)
                    if not member:
                        c.execute(
                            db.user_videos.insert().values(
                                user_id=owner, video_id=video_id, created_at=now
                            )
                        )
                    pending = c.scalar(
                        sa.select(db.jobs.c.job_id)
                        .where(
                            db.jobs.c.video_id == video_id,
                            db.jobs.c.kind == "import",
                            db.jobs.c.state.in_(["queued", "running"]),
                        )
                        .limit(1)
                    )
                    kind = "attach" if pending or video["status"] == "ready" else "import"
                    job = self._new_job(
                        c,
                        kind,
                        {"original_url": canonical_url(video_id)},
                        video_id=video_id,
                        generation=video["generation"],
                    )
                    if kind == "attach" and video["status"] == "ready":
                        c.execute(
                            db.jobs.update()
                            .where(db.jobs.c.job_id == job["job_id"])
                            .values(state="completed", stage="ready", result={"video_id": video_id})
                        )
                    elif kind == "import":
                        c.execute(
                            db.videos.update()
                            .where(db.videos.c.video_id == video_id)
                            .values(status="queued")
                        )
                items.append(
                    dict(
                        input_index=position,
                        outcome="existing" if member else "accepted",
                        video_id=video_id,
                        job_id=job["job_id"],
                    )
                )
        return items

    def _delete_private(self, video_id):
        from .repository import row

        with self.db.write() as c:
            owner = self._actor(c)
            self._require_video(c, video_id, owner)
            video = row(c, db.videos, db.videos.c.video_id == video_id)
            c.execute(
                db.user_videos.delete().where(
                    db.user_videos.c.user_id == owner, db.user_videos.c.video_id == video_id
                )
            )
            remaining = c.scalar(
                sa.select(sa.func.count())
                .select_from(db.user_videos)
                .where(db.user_videos.c.video_id == video_id)
            )
            for job in (
                c.execute(
                    sa.select(db.jobs).where(
                        db.jobs.c.owner_id == owner, db.jobs.c.state.in_(["queued", "running"])
                    )
                )
                .mappings()
                .all()
            ):
                uses = job["video_id"] == video_id or any(
                    source["video_id"] == video_id for source in job["payload"].get("sources", [])
                )
                if uses and not (remaining and job["kind"] == "import"):
                    values = dict(cancel_requested=True)
                    if job["state"] == "queued":
                        values.update(state="cancelled", stage="cancelled", error_code="cancelled")
                    c.execute(
                        db.jobs.update().where(db.jobs.c.job_id == job["job_id"]).values(**values)
                    )
            kind = "detach" if remaining else "delete"
            job = self._new_job(c, kind, {}, video_id=video_id, generation=video["generation"])
            if remaining:
                c.execute(
                    db.jobs.update()
                    .where(db.jobs.c.job_id == job["job_id"])
                    .values(
                        state="completed", stage="completed", result={"removed_from_library": True}
                    )
                )
            else:
                c.execute(
                    db.videos.update()
                    .where(db.videos.c.video_id == video_id)
                    .values(status="deleting")
                )
            return row(c, db.jobs, db.jobs.c.job_id == job["job_id"])
