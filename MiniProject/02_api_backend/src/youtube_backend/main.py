import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .admin import MemberUpdate, change_member, require_admin
from .auth import AuthService, GoogleLogin, actor_id, public_user
from .chat_review import Feedback, ReviewUpdate
from .config import Settings
from .database import SCHEMA_REVISION, Database
from .errors import AppError
from .quota_status import QuotaStatus
from .repository import Repository
from .runtime import ManagedAdapters
from .schemas import (
    Accepted,
    AnalysisRequest,
    ArtifactRequest,
    ChatRequest,
    ChatResponse,
    ConversationList,
    ConversationResponse,
    ErrorResponse,
    ImportRequest,
    ImportResponse,
    JobResponse,
    QuizSubmission,
    ResearchRequest,
    ResumeRequest,
    TranscriptResponse,
    VideoList,
)
from .telemetry import request_id
from .worker import Worker

logger = logging.getLogger(__name__)
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[\w.-]+$")
]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def create_app(settings=None, database=None, adapters=None):
    settings = settings or Settings()
    database = database or Database(settings.database_url)
    repository = Repository(database, settings)
    runtime = ManagedAdapters(settings, repository, adapters)
    worker = Worker(repository, runtime, settings, report_liveness=False)
    auth = AuthService(database, settings)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await runtime.start()
            yield
        finally:
            try:
                await runtime.close()
            finally:
                database.close()

    app = FastAPI(
        title="YouTube Knowledge API (02)",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env in {"development", "test"} else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env in {"development", "test"} else None,
        description="Account-scoped backend. Fixture mode is explicitly synthetic. "
        "Long tasks return 202 and are polled through /api/jobs/{job_id}.",
        responses={
            code: {"model": ErrorResponse}
            for code in (400, 401, 403, 404, 409, 422, 429, 500, 502, 503, 504)
        },
    )
    app.state.settings, app.state.repository = settings, repository
    app.state.worker, app.state.adapters = worker, runtime
    app.state.auth = auth

    def error_response(request, code, message, status, retryable=False, job_id=None):
        detail = dict(
            code=code,
            message=message,
            retryable=retryable,
            request_id=getattr(request.state, "request_id", str(uuid4())),
        )
        if job_id:
            detail["job_id"] = job_id
        return JSONResponse(status_code=status, content={"error": detail})

    @app.middleware("http")
    async def correlation(request, call_next):
        correlation_id = str(uuid4())
        request.state.request_id = correlation_id
        token = request_id.set(correlation_id)
        identity_token = actor_id.set(None)
        started = time.monotonic()
        try:
            try:
                if (
                    settings.auth_enabled
                    and request.url.path.startswith("/api/")
                    and (
                        request.url.path not in {"/api/auth/challenge", "/api/auth/google"}
                        and request.method != "OPTIONS"
                    )
                ):
                    from starlette.concurrency import run_in_threadpool

                    user, _ = await run_in_threadpool(
                        auth.current, request, mutate=request.method not in {"GET", "HEAD"}
                    )
                    actor_id.set(user["user_id"])
                    request.state.user = user
                response = await call_next(request)
                if request.url.path.startswith("/api/"):
                    response.headers["Cache-Control"] = "no-store"
            except AppError as error:
                response = error_response(request, error.code, error.message, error.status_code)
            except Exception:
                # No raw dependency exception, query string, body, or API key in logs/responses.
                response = error_response(request, "internal_error", "Unexpected server error", 500)
            if request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            response.headers["X-Request-ID"] = correlation_id
            response.headers["X-Adapter-Mode"] = settings.adapter_mode
            logger.info(
                "http_request request_id=%s method=%s status=%s latency_ms=%.1f",
                correlation_id,
                request.method,
                response.status_code,
                (time.monotonic() - started) * 1000,
            )
            return response
        finally:
            actor_id.reset(identity_token)
            request_id.reset(token)

    # Registered last so CORS wraps authentication failures created by correlation
    # itself. A credentialed frontend must be able to read 401/403 and clear state.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.auth_trusted_origins or [settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "X-Adapter-Mode", "Location"],
    )

    @app.exception_handler(AppError)
    async def app_error(request, error):
        return error_response(
            request, error.code, error.message, error.status_code, error.retryable
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(
            request, "validation_error", "Request does not match the API schema", 422
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(
            request, "http_error", "HTTP request could not be handled", error.status_code
        )

    @app.get("/health")
    def health():
        database.check_schema()
        from .quota import QuotaBroker

        try:
            QuotaBroker(repository).policy()
            policy_state = "operator_attested"
        except AppError:
            policy_state = "unverified"
        from .workspace import worker_status

        return dict(
            status="ok",
            worker=worker_status(settings),
            schema_revision=SCHEMA_REVISION,
            mode=settings.adapter_mode,
            adapters_configured=settings.adapter_mode != "unavailable",
            live_provider_verified=False,
            full_pair_preflight=settings.backend_full_preflight,
            single_user=not settings.auth_enabled,
            authentication_required=settings.auth_enabled,
            gemini_free_policy=policy_state,
            media_contract_version=2,
            capabilities=runtime.capabilities,
            integration_profile=settings.backend_integration_profile
            if settings.adapter_mode == "custom"
            else None,
            synthetic_data=settings.adapter_mode == "fixture"
            or settings.backend_integration_profile == "offline",
        )

    @app.post("/api/videos/import", response_model=ImportResponse, status_code=202)
    async def import_videos(body: ImportRequest):
        await runtime.require("ingest", "index", "inventory")
        return dict(jobs=repository.import_urls(body.urls), mode=settings.adapter_mode)

    @app.get("/api/providers")
    async def providers():
        from .provider_status import provider_status

        return await provider_status(repository, runtime)

    @app.post("/api/videos/{video_id}/trial-reindex", response_model=Accepted, status_code=202)
    async def trial_reindex_job(video_id: str, idempotency_key: IdempotencyKey = None):
        from .job_actions import trial_reindex

        await runtime.start()
        if not callable(getattr(runtime.adapter, "reindex", None)):
            raise AppError(
                "reindex_unsupported", "The mounted adapter has no trial reindex worker", 409
            )
        return accepted(trial_reindex(repository, video_id, idempotency_key))

    @app.post("/api/jobs/{job_id}/regenerate", response_model=Accepted, status_code=202)
    async def regenerate_job(job_id: str, idempotency_key: IdempotencyKey = None):
        from .job_actions import regenerate

        await runtime.start()
        return accepted(
            regenerate(
                repository,
                job_id,
                idempotency_key,
                getattr(runtime.adapter, "fresh_generation", ()),
            )
        )

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str):
        return repository.public_job(repository.get_job(job_id))

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str):
        return repository.public_job(repository.cancel(job_id))

    def accepted(job, research=False):
        body = dict(job_id=job["job_id"], state=job["state"])
        if research:
            body["run_id"] = job["job_id"]
        return JSONResponse(
            status_code=202, content=body, headers={"Location": f"/api/jobs/{job['job_id']}"}
        )

    @app.post("/api/jobs/{job_id}/retry", response_model=Accepted, status_code=202)
    def retry_job(job_id: str):
        return accepted(repository.retry(job_id))

    @app.get("/api/videos", response_model=VideoList)
    def list_videos(
        limit: Limit = 50,
        offset: Offset = 0,
        channel_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        playlist_id: str | None = None,
    ):
        if playlist_id is not None:
            raise AppError("unsupported_filter", "Playlist filtering is not implemented", 422)
        if date_from and date_to and date_from > date_to:
            raise AppError("invalid_date_range", "date_from must be on or before date_to", 422)
        return repository.list_videos(limit, offset, channel_id, date_from, date_to)

    @app.get("/api/videos/{video_id}/transcript", response_model=TranscriptResponse)
    def transcript(video_id: str, limit: Limit = 100, offset: Offset = 0):
        return repository.transcript(video_id, limit, offset)

    @app.delete("/api/videos/{video_id}", response_model=Accepted, status_code=202)
    async def delete_video(video_id: str):
        await runtime.require("delete")
        return accepted(repository.delete_video(video_id))

    @app.post("/api/chat", response_model=ChatResponse, responses={202: {"model": Accepted}})
    async def chat(body: ChatRequest, request: Request, idempotency_key: IdempotencyKey = None):
        await runtime.require(
            *(["answer"] if body.mode == "general" else ["answer", "evidence", "inventory"])
        )
        job = repository.enqueue("chat", body.model_dump(mode="json"), idempotency_key)
        if (
            settings.auth_enabled
            and settings.adapter_mode != "fixture"
            and job["state"] in {"queued", "running", "paused"}
        ):
            # The dedicated worker owns long provider work. A quick durable acknowledgment
            # gives clients a job ID immediately and keeps cancellation available.
            return accepted(job)
        if job["state"] == "queued":
            await worker.run_once(job["job_id"])
        job = repository.get_job(job["job_id"])
        if job["state"] == "completed":
            return dict(
                repository.chat_result(job), sources_available=repository.sources_available(job)
            )
        if job["state"] in {"queued", "running", "paused"}:
            return accepted(job)
        code = job["error_code"] or "task_failed"
        status = (
            503
            if code
            in {
                "dependency_unavailable",
                "free_tier_unverified",
                "free_model_unverified",
                "gemini_broker_required",
                "quota_policy_mismatch",
                "provider_unavailable",
            }
            else 429
            if code in {"quota_wait", "provider_rate_limited"}
            else 504
            if code == "task_timeout"
            else 422
            if code
            in {
                "invalid_video_time",
                "invalid_video_time_range",
                "video_time_out_of_bounds",
                "ambiguous_video_time",
            }
            else (409 if code in {"cancelled", "source_changed"} else 502)
        )
        return error_response(
            request,
            code,
            "Chat could not be completed; inspect the job status",
            status,
            job["retryable"],
            job["job_id"],
        )

    @app.post("/api/chat/check")
    def chat_check(body: ChatRequest):
        from .moderation import precheck

        return precheck(repository, body.model_dump(mode="json"))

    @app.get("/api/chat/policy")
    def chat_policy():
        from .moderation import POLICY_VERSION

        return dict(
            policy_version=POLICY_VERSION,
            review_enabled=settings.chat_review_enabled,
            review_notice="บทสนทนาอาจได้รับการตรวจโดยผู้ดูแลเพื่อปรับปรุงบริการ",
            moderation_retention_days=settings.moderation_retention_days,
        )

    @app.put("/api/messages/{message_id}/feedback")
    def put_feedback(message_id: str, body: Feedback):
        from .chat_review import set_feedback

        return set_feedback(repository, message_id, body)

    @app.delete("/api/messages/{message_id}/feedback")
    def remove_feedback(message_id: str):
        from .chat_review import set_feedback

        return set_feedback(repository, message_id)

    @app.get("/api/messages/{message_id}/feedback")
    def get_feedback(message_id: str):
        from .chat_review import feedback_for, owned_message

        with database.read() as c:
            owner = owned_message(repository, c, message_id)
            return dict(message_id=message_id, feedback=feedback_for(c, owner, message_id))

    @app.get("/api/admin/chat-reviews")
    def chat_reviews(
        limit: Limit = 50,
        offset: Offset = 0,
        status: Annotated[str, Query(pattern="^(pending|all|new|in_review|reviewed)$")] = "pending",
        rating: Annotated[str | None, Query(pattern="^(like|dislike)$")] = None,
        label: Annotated[str | None, Query(max_length=40)] = None,
        q: Annotated[str, Query(max_length=200)] = "",
        after: Annotated[float | None, Query(ge=0, le=253402300799)] = None,
        before: Annotated[float | None, Query(ge=0, le=253402300799)] = None,
    ):
        from .chat_review import review_list

        if after is not None and before is not None and after > before:
            raise AppError("invalid_date_range", "after must be on or before before", 422)
        return review_list(
            repository,
            limit=limit,
            offset=offset,
            status=status,
            rating=rating,
            label=label,
            q=q,
            after=after,
            before=before,
        )

    @app.get("/api/admin/chat-reviews/{case_id}")
    def review_detail(case_id: str):
        from .chat_review import detail

        return detail(repository, case_id=case_id)

    @app.patch("/api/admin/chat-reviews/{case_id}")
    def review_update(case_id: str, body: ReviewUpdate):
        from .chat_review import update_case

        return update_case(repository, case_id, body)

    @app.get("/api/admin/chat-messages")
    def admin_messages(limit: Limit = 50, offset: Offset = 0, rating: str | None = None):
        from .chat_review import normal_messages

        if rating not in {None, "like", "dislike"}:
            raise AppError("invalid_rating", "Invalid feedback rating", 422)
        return normal_messages(repository, limit, offset, rating)

    @app.get("/api/admin/chat-messages/{message_id}")
    def admin_message_detail(message_id: str):
        from .chat_review import detail

        return detail(repository, message_id=message_id)

    @app.get("/api/admin/chat-messages/{message_id}/context")
    def admin_message_context(message_id: str, limit: Limit = 20, offset: Offset = 0):
        import sqlalchemy as sa

        from . import database as db
        from .chat_review import audit, message_detail, require_review

        with database.write() as c:
            admin = require_review(repository, c)
            data, owner = message_detail(c, message_id)
            items = (
                c.execute(
                    sa.select(db.messages)
                    .where(db.messages.c.conversation_id == data["conversation_id"])
                    .order_by(db.messages.c.created_at, db.messages.c.message_id)
                    .limit(limit)
                    .offset(offset)
                )
                .mappings()
                .all()
            )
            audit(
                c,
                admin,
                owner,
                "chat_context_open",
                message_id=message_id,
                limit=limit,
                offset=offset,
            )
            return dict(items=[dict(item) for item in items], limit=limit, offset=offset)

    @app.delete("/api/conversations/{conversation_id}")
    def erase_conversation(conversation_id: str):
        from .chat_review import delete_conversation

        return delete_conversation(repository, conversation_id)

    @app.post("/api/analysis", response_model=Accepted, status_code=202)
    async def analysis(body: AnalysisRequest, idempotency_key: IdempotencyKey = None):
        await runtime.require("analyze", "evidence", "inventory")
        return accepted(
            repository.enqueue("analysis", body.model_dump(mode="json"), idempotency_key)
        )

    @app.post("/api/research", response_model=Accepted, status_code=202)
    async def research(body: ResearchRequest, idempotency_key: IdempotencyKey = None):
        await runtime.require("research", "evidence", "inventory")
        return accepted(
            repository.enqueue("research", body.model_dump(mode="json"), idempotency_key), True
        )

    @app.get("/api/research/{run_id}")
    def research_status(run_id: str, after_event_id: Offset = 0, limit: Limit = 100):
        job = repository.get_job(run_id)
        if job["kind"] != "research":
            raise AppError("run_not_found", "Research run not found", 404)
        return dict(
            **repository.public_job(job),
            events=repository.list_events(run_id, after_event_id, limit),
        )

    @app.post("/api/research/{run_id}/cancel", response_model=JobResponse)
    def cancel_research(run_id: str):
        job = repository.get_job(run_id)
        if job["kind"] != "research":
            raise AppError("run_not_found", "Research run not found", 404)
        return repository.public_job(repository.cancel(run_id))

    @app.post("/api/learning-artifacts", response_model=Accepted, status_code=202)
    async def create_artifact(body: ArtifactRequest, idempotency_key: IdempotencyKey = None):
        await runtime.require("artifact", "evidence", "inventory")
        return accepted(
            repository.enqueue("artifact", body.model_dump(mode="json"), idempotency_key)
        )

    @app.post(
        "/api/learning-artifacts/{artifact_id}/submit", response_model=Accepted, status_code=202
    )
    async def submit_quiz(
        artifact_id: str, body: QuizSubmission, idempotency_key: IdempotencyKey = None
    ):
        await runtime.require("artifact")
        return accepted(repository.enqueue_quiz(artifact_id, body.answers, idempotency_key))

    @app.get("/api/learning-artifacts/{artifact_id}")
    def get_artifact(artifact_id: str):
        return repository.artifact(artifact_id)

    @app.get("/api/conversations", response_model=ConversationList)
    def conversations(
        limit: Limit = 20, offset: Offset = 0, q: Annotated[str, Query(max_length=200)] = ""
    ):
        return repository.conversations(limit, offset, q)

    @app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
    def history(conversation_id: str, limit: Limit = 50, offset: Offset = 0):
        return repository.conversation(conversation_id, limit, offset)

    @app.get("/api/auth/challenge")
    def login_challenge(request: Request, response: Response):
        return auth.challenge(request, response)

    @app.get("/api/v2/videos/{video_id}/evidence")
    def media_evidence(video_id: str):
        from .media import MediaStore

        return MediaStore(repository).evidence(video_id)

    @app.get("/api/media/assets/{asset_id}")
    def media_asset(asset_id: str):
        from .media import MediaStore

        content, mime = MediaStore(repository).asset(asset_id)
        return Response(
            content,
            media_type=mime,
            headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
        )

    @app.post("/api/v2/videos/{video_id}/enrichment", status_code=202, response_model=Accepted)
    async def enrich(video_id: str, idempotency_key: IdempotencyKey = None):
        from .media import MediaStore

        await runtime.start()
        if not callable(getattr(runtime.adapter, "enrich", None)):
            raise AppError("dependency_unavailable", "Local media adapter is not connected", 503)
        return accepted(MediaStore(repository).enqueue(video_id, idempotency_key=idempotency_key))

    @app.get("/ready")
    def ready():
        from .workspace import worker_status

        database.check_schema()
        status = worker_status(settings)
        return JSONResponse(
            dict(status="ready" if status["ready"] else "degraded", worker=status),
            status_code=200 if status["ready"] else 503,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/member/jobs")
    def member_work(limit: Limit = 50, offset: Offset = 0, include_completed: bool = False):
        from .workspace import member_jobs

        return member_jobs(
            repository, limit=limit, offset=offset, include_completed=include_completed
        )

    @app.get("/api/worker-status")
    def processing_status():
        from .workspace import worker_status

        return worker_status(settings)

    @app.get("/api/quota", response_model=QuotaStatus, response_model_exclude_none=True)
    def member_quota():
        from .quota_status import quota_status

        return quota_status(repository)

    @app.get("/api/admin/quota", response_model=QuotaStatus, response_model_exclude_none=True)
    def project_quota():
        from .quota_status import quota_status

        return quota_status(repository, admin=True)

    @app.post("/api/jobs/{job_id}/resume", response_model=Accepted, status_code=202)
    def resume_job(job_id: str, body: ResumeRequest | None = None):
        from .job_resume import resume

        return accepted(resume(repository, job_id, body.moderation_token if body else None))

    @app.post("/api/auth/google")
    def google_login(body: GoogleLogin, request: Request, response: Response):
        return auth.login(request, response, body)

    @app.get("/api/auth/me")
    def me(request: Request):
        user, csrf = auth.current(request)
        return dict(user=public_user(user), csrf_token=csrf)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        return auth.logout(request, response)

    @app.get("/api/admin/users")
    def members(q: str = "", limit: Limit = 50, offset: Offset = 0):
        import sqlalchemy as sa

        from . import database as db

        with database.read() as c:
            require_admin(c)
            statement = sa.select(db.users).order_by(db.users.c.created_at)
            if q:
                statement = statement.where(
                    sa.or_(
                        db.users.c.name.contains(q, autoescape=True),
                        db.users.c.email.contains(q, autoescape=True),
                    )
                )
            items = c.execute(statement.limit(limit).offset(offset)).mappings().all()
            return dict(items=[public_user(user) for user in items], limit=limit, offset=offset)

    @app.post("/api/admin/users/{user_id}")
    def update_member(user_id: str, body: MemberUpdate):
        return change_member(database, user_id, body)

    @app.get("/api/admin/stats")
    def system_stats():
        import sqlalchemy as sa

        from . import database as db

        with database.read() as c:
            require_admin(c)
            return dict(
                users=c.scalar(sa.select(sa.func.count()).select_from(db.users)),
                jobs=dict(
                    c.execute(
                        sa.select(db.jobs.c.state, sa.func.count()).group_by(db.jobs.c.state)
                    ).all()
                ),
            )

    return app
