"""Explicit bounded live smoke using the existing member store, factory and Worker.

Stop the normal worker first: admission instrumentation is process-local. This is
an operator probe, not a login endpoint or a replacement queue implementation.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import sqlalchemy as sa
from learning_probe import ProbeBudget, implementation_fingerprints
from pydantic import Field
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.repository import Repository, digest
from youtube_backend.runtime import ManagedAdapters
from youtube_backend.schemas import (
    AnalysisRequest,
    ArtifactRequest,
    ChatRequest,
    QuizSubmission,
    ResearchRequest,
)
from youtube_backend.worker import Worker


class QuizProbeRequest(QuizSubmission):
    artifact_id: str = Field(min_length=1, max_length=80)


REQUESTS = {
    "chat": ChatRequest,
    "analysis": AnalysisRequest,
    "artifact": ArtifactRequest,
    "research": ResearchRequest,
    "quiz_grade": QuizProbeRequest,
}


def validate_cases(cases):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 10:
        raise ValueError("Supply 1–10 explicit cases")
    names = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"name", "kind", "request"}:
            raise ValueError("Each case requires name, kind and request only")
        if not isinstance(case["name"], str) or not 1 <= len(case["name"]) <= 80:
            raise ValueError("Use a bounded case name")
        if case["name"] in names or case["kind"] not in REQUESTS:
            raise ValueError("Duplicate case name or unsupported operation")
        names.add(case["name"])
        REQUESTS[case["kind"]].model_validate(case["request"])
    return cases


async def execute(repo, runtime, cases, run_key):
    """Run once per case; replay/read checks must never dispatch a model again."""
    worker = Worker(repo, runtime, repo.settings, report_liveness=False)
    results = []
    for case in validate_cases(cases):
        key = f"worker-probe-{run_key}-{case['name']}"
        with repo.db.read() as connection:
            owner = repo._actor(connection)
            namespace = owner if repo.settings.auth_enabled else "legacy"
            if connection.scalar(
                sa.select(db.jobs.c.job_id).where(
                    db.jobs.c.idempotency_key == digest([namespace, case["kind"], key])
                )
            ):
                raise AppError("probe_run_key_used", "Choose a new explicit run key", 409)
        request = REQUESTS[case["kind"]].model_validate(case["request"]).model_dump(mode="json")

        def enqueue(kind=case["kind"], request=request, key=key):
            if kind == "quiz_grade":
                return repo.enqueue_quiz(request["artifact_id"], request["answers"], key)
            return repo.enqueue(kind, request, idempotency_key=key)

        job = enqueue()
        started = time.monotonic()
        await worker.run_once(job["job_id"])
        saved = repo.get_job(job["job_id"])
        # A smoke never leaves automatic retry work for the normal worker.
        if saved["state"] in {"queued", "running", "paused"}:
            repo.cancel(job["job_id"])
        final = repo.get_job(job["job_id"])
        replay = enqueue()
        item = {
            "name": case["name"],
            "kind": case["kind"],
            "job_id": job["job_id"],
            "state": saved["state"],
            "state_after_cleanup": final["state"],
            "error_code": saved.get("error_code"),
            "total_worker_ms": (time.monotonic() - started) * 1000,
            "same_job_on_replay": replay["job_id"] == job["job_id"],
            "result": saved.get("result"),
            "human_review": "pending",
        }
        if saved["result"] and case["kind"] == "artifact":
            item["artifacts"] = [
                repo.artifact(artifact_id) for artifact_id in saved["result"]["artifact_ids"]
            ]
        results.append(item)
        if saved["state"] not in {"completed", "partial"}:
            break  # No retries or selecting only successful samples.
    return results


async def run(settings, owner, cases, run_key, budget):
    database = Database(settings.database_url)
    repo = Repository(database, settings)
    runtime = ManagedAdapters(settings, repo)
    token = actor_id.set(owner)
    try:
        await runtime.start()
        with budget.bind():
            results = await execute(repo, runtime, cases, run_key)
        return {
            "results": results,
            "attempted_admissions": budget.calls,
            "reserved_input_estimate": budget.tokens,
            "dispatch_roundtrip_ms": budget.provider_ms,
            "implementation_sha256": implementation_fingerprints(),
            "semantic_acceptance": False,
            "external_identity_verified": False,
            "same_production_factory": settings.adapter_factory,
            "queue_wait_ms": None,
        }
    finally:
        actor_id.reset(token)
        await runtime.close()
        database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true", required=True)
    parser.add_argument("--workers-stopped", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--max-calls", required=True, type=int)
    parser.add_argument("--max-input-tokens", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cases = validate_cases(json.loads(args.cases.read_text("utf-8")))
    budget = ProbeBudget(args.max_calls, args.max_input_tokens)
    try:
        settings = Settings(_env_file=args.env_file)
        if (
            not settings.auth_enabled
            or settings.adapter_factory != "youtube_answers.team:create_adapters"
        ):
            raise ValueError("Use the authenticated production team factory")
        report = asyncio.run(run(settings, args.owner, cases, args.run_key, budget))
    except Exception as exc:
        report = {
            "error_code": exc.code if isinstance(exc, AppError) else type(exc).__name__,
            "attempted_admissions": budget.calls,
            "reserved_input_estimate": budget.tokens,
            "semantic_acceptance": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"results", "implementation_sha256"}}
        )
    )
    return (
        0
        if len(report.get("results", [])) == len(cases)
        and all(item["state"] in {"completed", "partial"} for item in report["results"])
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
