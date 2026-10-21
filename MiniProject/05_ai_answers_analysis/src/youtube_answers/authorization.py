"""Bind generation to 02's durable job owner and current library grants.

No identities come from requests, history, prompts or model output. 02 owns login,
resource reads, idempotency and publication; 04 owns permission-aware evidence.
"""

import copy

import sqlalchemy as sa
from youtube_backend import database as db

from .models import error


class MemberContext:
    def __init__(self, context, sources, kinds):
        self._context = context
        self._sources = tuple(s.model_copy(deep=True) for s in sources)
        self._kinds = kinds
        self._denied = False
        self._owner = None
        self._snapshot = None
        self._job = self._verify()

    def __getattr__(self, name):
        return getattr(self._context, name)

    def _verify(self):
        if self._denied:
            raise error("member_access_denied", "Execution is no longer authorized", status=403)
        self._context.check()  # Preserve cancellation/deadline/lease classifications.
        authorize = getattr(self._context, "authorize_sources", None)
        if not callable(authorize) or not all(
            hasattr(db, name) for name in ("users", "user_videos", "conversations")
        ):
            raise error("member_contract_unavailable", "Account-aware backend required", status=503)
        job = self.repository.check_execution(self.job_id, self.lease_token)
        owner = self._context.user_id
        if not owner or job.get("owner_id") != owner or job["kind"] not in self._kinds:
            raise error("member_access_denied", "Execution owner/kind mismatch", status=403)
        if self._owner is not None and owner != self._owner:
            raise error("member_access_denied", "Execution owner changed", status=403)
        authorize(self._sources)
        with self.repository.db.read() as connection:
            user = (
                connection.execute(sa.select(db.users).where(db.users.c.user_id == owner))
                .mappings()
                .first()
            )
            if not user or user["status"] != "active":
                raise error("member_access_denied", "Account is not active", status=403)
            grants = []
            for source in self._sources:
                grant = connection.execute(
                    sa.select(db.user_videos.c.created_at).where(
                        db.user_videos.c.user_id == owner,
                        db.user_videos.c.video_id == source.video_id,
                    )
                ).first()
                if grant is None:
                    raise error(
                        "member_access_denied", "Source is outside this library", status=403
                    )
                grants.append(
                    (source.video_id, source.generation, source.transcript_version, grant[0])
                )
            if job.get("conversation_id"):
                conversation_owner = connection.scalar(
                    sa.select(db.conversations.c.owner_id).where(
                        db.conversations.c.conversation_id == job["conversation_id"]
                    )
                )
                if conversation_owner != owner:
                    raise error(
                        "member_access_denied", "Conversation is not owned by actor", status=403
                    )
        snapshot = (owner, user["updated_at"], tuple(grants))
        if self._snapshot is not None and snapshot != self._snapshot:
            raise error("member_access_denied", "Account/source permissions changed", status=403)
        self._owner, self._snapshot = owner, snapshot
        return job

    def check(self):
        try:
            self._verify()
        except BaseException:
            self._denied = True
            raise

    def history(self, provided):
        self.check()
        history = self._job["payload"].get("history", [])
        if provided != history:
            self._denied = True
            raise error("member_access_denied", "History must match the durable job", status=403)
        return copy.deepcopy(history)

    def conversation(self, requested):
        if requested is not None and requested != self._job.get("conversation_id"):
            raise error("member_access_denied", "Conversation does not match this job", status=403)


def guard_context(context, sources, kinds):
    settings = getattr(context, "settings", None)
    if getattr(settings, "auth_enabled", False):
        return MemberContext(context, sources, kinds)
    if settings is not None and settings.app_env not in {"test", "development"}:
        raise error("authentication_required", "Authenticated generation is required", status=401)
    return context
