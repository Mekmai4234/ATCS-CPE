import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .config import Settings
from .database import Database
from .errors import AppError
from .integrations import load_adapters
from .repository import Repository
from .schemas import (
    Accepted,
    AnalysisRequest,
    ArtifactRequest,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ErrorResponse,
    ImportRequest,
    ImportResponse,
    JobResponse,
    ResearchRequest,
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
    adapters = adapters or load_adapters(settings, repository)
    worker = Worker(repository, adapters, settings)

    @asynccontextmanager
    async def lifespan(app):
        database.check_schema()
        repository.check_mode()
        yield
        database.close()

    app = FastAPI(
        title="YouTube Knowledge API (02)",
        version="0.1.0",
        lifespan=lifespan,
        description="Single-user prototype. Fixture mode is explicitly synthetic. "
        "Long tasks return 202 and are polled through /api/jobs/{job_id}.",
        responses={
            code: {"model": ErrorResponse} for code in (400, 404, 409, 422, 500, 502, 503, 504)
        },
    )
    app.state.settings, app.state.repository = settings, repository
    app.state.worker, app.state.adapters = worker, adapters
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "X-Adapter-Mode", "Location"],
    )

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
        started = time.monotonic()
        try:
            try:
                response = await call_next(request)
            except Exception:
                # No raw dependency exception, query string, body, or API key in logs/responses.
                response = error_response(request, "internal_error", "Unexpected server error", 500)
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
            request_id.reset(token)

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
        return dict(
            status="ok",
            schema_revision="0001",
            mode=settings.adapter_mode,
            adapters_configured=settings.adapter_mode != "unavailable",
            live_provider_verified=False,
            single_user=True,
        )

    @app.post("/api/videos/import", response_model=ImportResponse, status_code=202)
    def import_videos(body: ImportRequest):
        return dict(jobs=repository.import_urls(body.urls), mode=settings.adapter_mode)

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
    def delete_video(video_id: str):
        return accepted(repository.delete_video(video_id))

    @app.post("/api/chat", response_model=ChatResponse, responses={202: {"model": Accepted}})
    async def chat(body: ChatRequest, request: Request, idempotency_key: IdempotencyKey = None):
        job = repository.enqueue("chat", body.model_dump(mode="json"), idempotency_key)
        if job["state"] == "queued":
            await worker.run_once(job["job_id"])
        job = repository.get_job(job["job_id"])
        if job["state"] == "completed":
            return dict(job["result"], sources_available=repository.sources_available(job))
        if job["state"] in {"queued", "running"}:
            return accepted(job)
        code = job["error_code"] or "task_failed"
        status = (
            503
            if code == "dependency_unavailable"
            else 504
            if code == "task_timeout"
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

    @app.post("/api/analysis", response_model=Accepted, status_code=202)
    def analysis(body: AnalysisRequest, idempotency_key: IdempotencyKey = None):
        return accepted(
            repository.enqueue("analysis", body.model_dump(mode="json"), idempotency_key)
        )

    @app.post("/api/research", response_model=Accepted, status_code=202)
    def research(body: ResearchRequest, idempotency_key: IdempotencyKey = None):
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
    def create_artifact(body: ArtifactRequest, idempotency_key: IdempotencyKey = None):
        return accepted(
            repository.enqueue("artifact", body.model_dump(mode="json"), idempotency_key)
        )

    @app.get("/api/learning-artifacts/{artifact_id}")
    def get_artifact(artifact_id: str):
        return repository.artifact(artifact_id)

    @app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
    def history(conversation_id: str, limit: Limit = 50, offset: Offset = 0):
        return repository.conversation(conversation_id, limit, offset)

    return app
