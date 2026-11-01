"""Real captions/index trial; outbound admission stays in the EXISTING ledger.

The isolated member store owns transcript/index publication. A separately leased,
source-bound audit job in the original store owns every actual provider admission.
No key, policy or quota ledger is copied into the trial. The normal worker must be
stopped before invoking this operator-only function.
"""

import asyncio
import hashlib
import importlib.util
import secrets
import time
from contextlib import suppress
from pathlib import Path

import httpx
import sqlalchemy as sa
from learning_probe import ProbeBudget
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.schemas import Source
from youtube_backend.worker import Worker
from youtube_ingestion.config import IngestionSettings
from youtube_ingestion.integration import IngestionAdapters
from youtube_ingestion.service import IngestionService
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import GeminiEmbedder
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import BackendExecution, initialize


class LedgerExecution:
    def __init__(self, trial, ledger, video_id, gate):
        self.trial, self.ledger, self.video_id, self.gate = trial, ledger, video_id, gate

    async def gemini_call(self, callback, **request):
        self.trial.check()
        self.ledger.check()
        trial_job = self.trial.context.repository.check_execution(
            self.trial.context.job_id, self.trial.context.lease_token
        )
        ledger_job = self.ledger.repository.check_execution(
            self.ledger.job_id, self.ledger.lease_token
        )
        trial_scope = (
            {trial_job["video_id"]}
            if trial_job["kind"] == "import"
            else {s["video_id"] for s in trial_job["payload"].get("sources", [])}
        )
        if trial_scope != {self.video_id} or {
            s["video_id"] for s in ledger_job["payload"]["sources"]
        } != {self.video_id}:
            raise AppError("invalid_scope", "Trial and ledger scopes must match", 403)
        if request.get("role") != "embedding" or request.get("endpoint") not in {
            "countTokens",
            "embedContent",
        }:
            raise AppError("budget_role_denied", "This trial only admits embeddings", 403)
        credential = request.pop("credential_sha256", None)
        expected = hashlib.sha256(
            self.ledger.settings.gemini_api_key.get_secret_value().encode()
        ).hexdigest()
        if not isinstance(credential, str) or not secrets.compare_digest(credential, expected):
            raise AppError("credential_mismatch", "Trial credential must match ledger", 403)
        self.gate()
        value = await self.ledger.gemini_call(callback, **request)
        self.trial.check()
        self.ledger.check()
        return value


class TrialEmbedder(GeminiEmbedder):
    def __init__(self, config, ledger, video_id):
        super().__init__(config)
        self.ledger, self.video_id = ledger, video_id
        self.interrupted, self.attempts = False, 0

    def gate(self):
        if self.attempts == 8 and not self.interrupted:
            self.interrupted = True
            raise asyncio.CancelledError("Intentional trial interruption between batches")
        self.attempts += 1

    async def embed(self, *args, execution=None, **kwargs):
        return await super().embed(
            *args,
            execution=LedgerExecution(execution, self.ledger, self.video_id, self.gate),
            **kwargs,
        )


async def run(settings, owner, video_id, state, run_key):
    if settings.embedding_provider != "gemini" or not settings.auth_enabled:
        raise ValueError("Use the existing authenticated Gemini embedding configuration")
    state = Path(state).resolve()
    if state.exists():
        raise ValueError("Choose a new trial directory")
    helper_path = Path(__file__).parents[2] / "03_video_ingestion/scripts/acceptance_check.py"
    spec = importlib.util.spec_from_file_location("trial_captions_helpers", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    original = Database(settings.database_url)
    repo = Repository(original, settings)
    actor = actor_id.set(owner)
    audit = pulse = None
    trial_db = knowledge = ingestion = embedder = None
    phases = []
    started = time.monotonic()
    try:
        audit = repo.enqueue(
            "research",
            {
                "goal": "[TRIAL INDEX AUDIT] Provider accounting only",
                "scope": {"video_ids": [video_id]},
            },
            idempotency_key="trial-index-" + run_key,
        )
        audit = repo.claim(audit["job_id"])
        if not audit:
            raise AppError("trial_audit_unavailable", "Audit lease unavailable", 409)
        ledger = ExecutionContext(
            repo, audit["job_id"], audit["lease_token"], audit["deadline_at"], settings
        )

        async def heartbeat():
            while True:
                await asyncio.sleep(settings.job_lease_seconds / 3)
                repo.heartbeat(audit["job_id"], audit["lease_token"])

        pulse = asyncio.create_task(heartbeat())
        state.mkdir(parents=True)
        trial = Settings(
            _env_file=None,
            app_env="test",
            auth_enabled=True,
            session_cookie_secure=False,
            google_client_id="trial-fixture-identity",
            adapter_mode="custom",
            adapter_factory="trial_only:real_captions_and_embeddings",
            backend_full_preflight=False,
            backend_integration_profile="live",
            job_retry_base_seconds=0,
            database_url="sqlite:///" + (state / "app.db").as_posix(),
            chroma_persist_dir=str(state / "chroma"),
        )
        trial_db = Database(trial.database_url)
        upgrade_database(trial_db)
        initialize(trial_db)
        config = RagSettings(
            _env_file=None,
            **{
                **{name: getattr(settings, name) for name in RagSettings.model_fields},
                "chroma_persist_dir": str(state / "chroma"),
                "embedding_batch_size": 2,
            },
        )
        embedder = TrialEmbedder(config, ledger, video_id)
        knowledge = RagAdapters(
            settings=trial,
            repository=Repository(trial_db, trial),
            rag_settings=config,
            embedder=embedder,
        )
        captions = helper.RecordedCaptions()
        ingestion = IngestionService(IngestionSettings(_env_file=None), captions=captions)
        adapters = IngestionAdapters(ingestion, knowledge)
        app = create_app(trial, trial_db, adapters)
        worker = Worker(Repository(trial_db, trial), adapters, trial, report_liveness=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await helper.fixture_login(app, client)
            accepted = await client.post(
                "/api/videos/import", json={"urls": [f"https://youtu.be/{video_id}"]}
            )
            accepted.raise_for_status()
            job_id = accepted.json()["jobs"][0]["job_id"]
            # Reject a large transcript before ANY embedding request.
            raw_index = adapters.index

            async def bounded_index(source, transcript, context):
                if len(knowledge.rag.chunker.build(source, transcript)) > 8:
                    raise AppError(
                        "trial_scope_too_large", "Choose a clip with at most 8 chunks", 409
                    )
                return await raw_index(source, transcript, context)

            adapters.index = bounded_index
            for _phase in range(2):
                budget = ProbeBudget(12, 15000)
                try:
                    with budget.bind():
                        await worker.run_once(job_id)
                except asyncio.CancelledError:
                    pass
                phases.append({"calls": budget.calls, "input_estimate": budget.tokens})
                current = (await client.get("/api/jobs/" + job_id)).json()
                if current["state"] != "queued":
                    break
                if not embedder.interrupted:
                    break
            duplicate = await client.post(
                "/api/videos/import", json={"urls": [f"https://youtu.be/{video_id}"]}
            )
            current = (await client.get("/api/jobs/" + job_id)).json()
            transcript = (await client.get(f"/api/videos/{video_id}/transcript")).json()
            search_hits = None
            if current["state"] == "completed" and current["stage"] == "ready":
                # Read/search under a new trial lease, but retain the SAME original ledger lease.
                # Ingestion-only adapters intentionally do not mount research: use the
                # native repository under the already authenticated fixture member instead.
                with trial_db.read() as c:
                    trial_owner = c.scalar(sa.select(db.users.c.user_id))
                member = actor_id.set(trial_owner)
                try:
                    query = worker.repo.enqueue(
                        "research",
                        {"goal": "[TRIAL] Vector search only", "scope": {"video_ids": [video_id]}},
                    )
                    query = worker.repo.claim(query["job_id"])
                    context = ExecutionContext(
                        worker.repo,
                        query["job_id"],
                        query["lease_token"],
                        query["deadline_at"],
                        trial,
                    )
                    sources = [Source.model_validate(s) for s in query["payload"]["sources"]]
                    extra = ProbeBudget(2, 3000)
                    with extra.bind():
                        hits = await knowledge.rag.search(
                            "เนื้อหาในคลิปกล่าวถึงอะไร", sources, BackendExecution(context), top_k=3
                        )
                    phases.append({"calls": extra.calls, "input_estimate": extra.tokens})
                    search_hits = len(hits)
                    worker.repo.cancel(query["job_id"])
                    worker.repo.fail(
                        query["job_id"],
                        query["lease_token"],
                        AppError("cancelled", "Read verification complete", 409),
                    )
                finally:
                    actor_id.reset(member)
            if current["state"] in {"queued", "running", "paused"}:
                await client.post("/api/jobs/" + job_id + "/cancel")
            with original.read() as c:
                rows = (
                    c.execute(
                        sa.select(db.v2["reservations"]).where(
                            db.v2["reservations"].c.job_id == audit["job_id"]
                        )
                    )
                    .mappings()
                    .all()
                )
                ledger_counts = {
                    endpoint: sum(row["endpoint"] == endpoint for row in rows)
                    for endpoint in ("countTokens", "embedContent")
                }
            with trial_db.read() as c:
                trial_reservations = c.scalar(
                    sa.select(sa.func.count()).select_from(db.v2["reservations"])
                )
            return {
                "state": current["state"],
                "stage": current["stage"],
                "error_code": current.get("error_code"),
                "result": current.get("result"),
                "interrupted_between_batches": embedder.interrupted,
                "duplicate_same_job": duplicate.json()["jobs"][0]["job_id"] == job_id,
                "caption_fetches": captions.calls.get(video_id, 0),
                "segment_count": transcript.get("total"),
                "language": transcript.get("language"),
                "phases": phases,
                "original_ledger_calls": ledger_counts,
                "trial_ledger_rows": trial_reservations,
                "vector_search_hits": search_hits,
                "elapsed_ms": (time.monotonic() - started) * 1000,
                "embedding_provider": config.embedding_provider,
                "embedding_model": config.embedding_model,
                "embedding_dimensions": config.embedding_dimensions,
                "fingerprint": config.fingerprint,
                "identity": "fixture-google-verifier",
                "real_embeddings": True,
                "shared_original_ledger": True,
            }
    finally:
        if pulse:
            pulse.cancel()
            with suppress(asyncio.CancelledError):
                await pulse
        if knowledge:
            await knowledge.close()
        if ingestion:
            await ingestion.close()
        if trial_db:
            trial_db.close()
        if audit:
            repo.cancel(audit["job_id"])
            repo.fail(
                audit["job_id"],
                audit["lease_token"],
                AppError("cancelled", "Trial audit finished", 409),
            )
        actor_id.reset(actor)
        original.close()
