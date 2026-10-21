"""Compatibility factory name for 02's native authenticated worker flow.

No second membership/job contract is installed: 02 owns HTTP session/CSRF checks,
private jobs, admission and lifecycle; 04 consumes the durable ExecutionContext.
"""

from youtube_backend import database as db
from youtube_backend.integrations import ExecutionContext
from youtube_rag.manifest import BackendExecution

from .errors import failure
from .integration import create_adapters


async def create_member_adapters(*, settings, repository):
    if (
        getattr(settings, "auth_enabled", None) is not True
        or not all(hasattr(db, name) for name in ("users", "user_videos"))
        or not hasattr(ExecutionContext, "authorize_sources")
        or not hasattr(BackendExecution, "permission_scope")
        or not callable(getattr(repository, "_check_job_authorization", None))
    ):
        raise failure(
            "member_contract_unavailable",
            "Install and enable the native 02/04 ownership contract",
            503,
        )
    return await create_adapters(settings=settings, repository=repository)
