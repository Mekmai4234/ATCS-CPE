"""Explicit isolated acceptance runner; live provider calls require --live."""

import argparse
import asyncio
import json
import sys
import time
from importlib.resources import files
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator
from youtube_backend import database as backend_db
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.migration import upgrade_database
from youtube_backend.offline_model import OfflineModel
from youtube_backend.repository import Repository
from youtube_backend.schemas import ArtifactRequest, ResearchRequest, Schema, TranscriptResult
from youtube_backend.worker import Worker
from youtube_rag.config import RagSettings
from youtube_rag.manifest import initialize

from .config import AgentSettings
from .gemini import GeminiModel
from .integration import AgentAdapters

AUTHORIZATION_ERRORS = {
    "authentication_required",
    "authorization_unavailable",
    "permission_denied",
    "member_access_denied",
    "member_authority_unavailable",
}


def default_dataset():
    """Installed package resource; consumers need no repository-level fixtures directory."""
    return files("youtube_agent").joinpath("data", "acceptance.json")


class Case(Schema):
    id: str = Field(min_length=1, max_length=100)
    operation: Literal["research", "artifact"]
    request: dict
    expected_states: list[Literal["completed", "partial", "failed"]] = Field(
        default_factory=lambda: ["completed", "partial"], min_length=1
    )
    max_steps: int | None = Field(default=None, ge=1, le=100)
    review: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def request_schema(self):
        schema = ResearchRequest if self.operation == "research" else ArtifactRequest
        self.request = schema.model_validate(self.request).model_dump(mode="json")
        return self


class Dataset(Schema):
    label: str = Field(min_length=1, max_length=200)
    provenance: Literal["synthetic", "exported_transcripts"]
    videos: list[TranscriptResult] = Field(min_length=1, max_length=10)
    cases: list[Case] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def identities(self):
        ids = {v.video_id for v in self.videos}
        if len(ids) != len(self.videos) or len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Dataset video and case IDs must be unique")
        if any(not set(c.request["scope"]["video_ids"]).issubset(ids) for c in self.cases):
            raise ValueError("Case scope must reference dataset videos")
        return self


class DatasetAdapters(AgentAdapters):
    """Import an explicit transcript export, never fetch a URL or synthesize captions."""

    async def ingest(self, video_id, context):
        context.check()
        return self.transcripts[video_id]


async def evaluate(dataset_path, state, *, live=False, legacy_test=False):
    if live and legacy_test:
        raise ValueError("Legacy test mode cannot call live providers")
    dataset = Dataset.model_validate_json(
        dataset_path.read_text(encoding="utf-8")
        if hasattr(dataset_path, "read_text")
        else Path(dataset_path).read_text(encoding="utf-8")
    )
    state = Path(state).resolve()
    # A new directory prevents fixture/live relabelling and accidental mutation of user indexes.
    state.mkdir(parents=True, exist_ok=False)
    agent_config = AgentSettings() if live else AgentSettings(_env_file=None)
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=not legacy_test,
        adapter_mode="custom" if live else "fixture",
        adapter_factory="youtube_agent.integration:create_adapters" if live else None,
        backend_integration_profile="live" if live else "offline",
        database_url=f"sqlite:///{(state / 'app.db').as_posix()}",
        job_lease_seconds=60,
        job_max_attempts=1,
        agent_timeout_seconds=agent_config.agent_timeout_seconds,
        llm_model=agent_config.llm_model,
    )
    rag_values = (
        {}
        if live
        else {
            "embedding_provider": "fixture",
            "embedding_model": "fixture-hash-v1",
            "embedding_dimensions": 64,
        }
    )
    rag_config = RagSettings(
        _env_file=None,
        gemini_api_key=agent_config.gemini_api_key,
        chroma_persist_dir=state / "chroma",
        **rag_values,
    )
    database = Database(settings.database_url)
    adapters = model = actor_token = None
    try:
        upgrade_database(database)
        initialize(database)
        if not legacy_test:
            # A synthetic member owns only this NEW evaluation database, never existing content.
            from youtube_backend.auth import actor_id

            owner = str(uuid4())
            now = time.time()
            with database.write() as connection:
                connection.execute(
                    backend_db.users.insert().values(
                        user_id=owner,
                        google_sub=f"evaluation-fixture:{owner}",
                        name="[FIXTURE] Evaluation member",
                        role="user",
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                )
            actor_token = actor_id.set(owner)
        repository = Repository(database, settings)
        model = GeminiModel(agent_config) if live else OfflineModel(agent_config.llm_model)
        adapters = DatasetAdapters(
            settings=settings,
            repository=repository,
            agent_settings=agent_config,
            model=model,
            rag_settings=rag_config,
        )
        adapters.transcripts = {v.video_id: v for v in dataset.videos}
        worker = Worker(repository, adapters, settings)
        for video in dataset.videos:
            item = repository.import_urls([f"https://youtu.be/{video.video_id}"])[0]
            await worker.run_once(item["job_id"])
            if repository.get_job(item["job_id"])["stage"] != "ready":
                raise AppError("evaluation_import_failed", "Dataset indexing did not complete", 502)
        cases = []
        for case in dataset.cases:
            # Case overrides are intentional test scenarios, not a new runtime env profile.
            adapters.agent.settings = agent_config.model_copy(
                update={"agent_max_steps": case.max_steps or agent_config.agent_max_steps}
            )
            started = time.monotonic()
            job = repository.enqueue(case.operation, case.request)
            await worker.run_once(job["job_id"])
            completed = repository.get_job(job["job_id"])
            result = completed["result"]
            cases.append(
                {
                    "id": case.id,
                    "operation": case.operation,
                    "state": completed["state"],
                    "error_code": completed["error_code"],
                    "contract_passed": (
                        completed["state"] in case.expected_states
                        and completed["error_code"] not in AUTHORIZATION_ERRORS
                    ),
                    "wall_latency_ms": (time.monotonic() - started) * 1000,
                    "provider_metadata": result.get("provider_metadata") if result else None,
                    "result": result,
                    "manual_review": {"required": True, "passed": None, "criteria": case.review},
                }
            )
        return {
            "dataset": dataset.label,
            "provenance": dataset.provenance,
            "mode": "live-gemini" if live else "offline-fixture",
            "authorization_mode": "isolated-legacy-test"
            if legacy_test
            else "isolated-member-fixture",
            "semantic_quality_verified": False,
            "limitation": "Contract checks and timings do not establish semantic quality. "
            "Review each output against its source transcript.",
            "contract_passed": all(c["contract_passed"] for c in cases),
            "cases": cases,
        }
    finally:
        try:
            if adapters is not None:
                await adapters.close()
            elif model is not None:
                await model.close()
        finally:
            try:
                database.close()
            finally:
                if actor_token is not None:
                    actor_id.reset(actor_token)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Module 06 isolated research/artifact acceptance")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=default_dataset(),
    )
    parser.add_argument("--state", type=Path, required=True, help="New isolated directory only")
    parser.add_argument(
        "--output", type=Path, required=True, help="JSON report with review outputs"
    )
    parser.add_argument("--live", action="store_true", help="Explicitly call paid Gemini services")
    parser.add_argument(
        "--legacy-test",
        action="store_true",
        help="Offline-only regression in a NEW database with auth disabled only there",
    )
    args = parser.parse_args()
    try:
        report = asyncio.run(
            evaluate(args.dataset, args.state, live=args.live, legacy_test=args.legacy_test)
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "contract_passed": report["contract_passed"],
                    "mode": report["mode"],
                    "authorization_mode": report["authorization_mode"],
                    "cases": len(report["cases"]),
                }
            )
        )
        return 0 if report["contract_passed"] else 1
    except AppError as exc:
        print(json.dumps({"error_code": exc.code}), file=sys.stderr)
    except (ValueError, OSError):
        print(
            "Evaluation failed; use a valid dataset and a NEW isolated state directory.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
