"""Explicit bounded live learning probe through the EXISTING shared quota ledger.

This creates audited jobs/artifacts in the selected application store. It never creates
an isolated fresh quota ledger, changes policy, retries a rejected call or clears usage.
"""

import argparse
import asyncio
import hashlib
import json
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext


def stop_owned(repo, job, error):
    current = repo.get_job(job["job_id"], internal=True)
    if current["state"] == "running" and current["lease_token"] == job["lease_token"]:
        repo.fail(job["job_id"], job["lease_token"], error)
        repo.cancel(job["job_id"])


class ProbeBudget:
    def __init__(self, max_calls, max_tokens):
        if (
            type(max_calls) is not int
            or not 1 <= max_calls <= 12
            or type(max_tokens) is not int
            or not 1 <= max_tokens <= 500000
        ):
            raise ValueError("Explicit bounded probe budget required")
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.calls = self.tokens = 0
        self.provider_ms = 0

    def admit(self, tokens):
        if (
            type(tokens) is not int
            or tokens <= 0
            or self.calls >= self.max_calls
            or self.tokens + tokens > self.max_tokens
        ):
            raise AppError("probe_budget_exhausted", "Predeclared live probe budget exhausted", 409)
        self.calls += 1
        self.tokens += tokens  # Uncertain/failed calls retain their full allowance.

    @contextmanager
    def bind(self):
        # 05 uses reserve/dispatch/settle directly; 04/06 use call(). Instrument
        # their common SQL boundary so no consumer can bypass the trial cap.
        from youtube_backend.quota import QuotaBroker

        reserve, dispatch, settle = QuotaBroker.reserve, QuotaBroker.dispatch, QuotaBroker.settle
        starts = {}

        def bounded_reserve(broker, context, **request):
            self.admit(request["input_tokens"])
            return reserve(broker, context, **request)

        def measured_dispatch(broker, context, reservation_id):
            value = dispatch(broker, context, reservation_id)
            starts[reservation_id] = time.monotonic()
            return value

        def measured_settle(broker, reservation_id, **reply):
            try:
                return settle(broker, reservation_id, **reply)
            finally:
                started = starts.pop(reservation_id, None)
                if started is not None:
                    self.provider_ms += (time.monotonic() - started) * 1000

        with (
            patch.object(QuotaBroker, "reserve", bounded_reserve),
            patch.object(QuotaBroker, "dispatch", measured_dispatch),
            patch.object(QuotaBroker, "settle", measured_settle),
        ):
            yield


async def probe(settings, *, owner, video_id, topic, budget, types, run_key):
    import sqlalchemy as sa
    from youtube_backend import database as db
    from youtube_backend.database import Database
    from youtube_backend.full_pair import check_pair
    from youtube_backend.quota import QuotaBroker
    from youtube_backend.repository import Repository, digest
    from youtube_backend.runtime import ManagedAdapters
    from youtube_backend.schemas import ArtifactResult, Source
    from youtube_backend.validation import validate_result

    check_pair(settings)
    database = Database(settings.database_url)
    repo = Repository(database, settings)
    runtime = ManagedAdapters(settings, repo)
    # Factories must use precisely the selected full snapshot, including secrets.
    config = settings.services()
    token = actor_id.set(owner)
    results = []
    try:
        broker = QuotaBroker(repo)
        broker.access(settings.llm_model, "generateContent", "agent")
        broker.access(settings.llm_model, "countTokens", "agent")
        await runtime.start()
        for kind in types:
            request = dict(
                type=kind, topic=topic, scope={"video_ids": [video_id]}, level="beginner", days=2
            )
            idempotency_key = f"probe-{run_key}-{kind}"
            with database.read() as c:
                repo._actor(c)
                existing = c.scalar(
                    sa.select(db.jobs.c.job_id).where(
                        db.jobs.c.idempotency_key == digest([owner, "artifact", idempotency_key])
                    )
                )
            if existing:
                results.append(
                    dict(type=kind, state="blocked", reason="probe_run_key_already_used")
                )
                break
            queued = repo.enqueue("artifact", request, idempotency_key=idempotency_key)
            if queued["state"] != "queued":
                results.append(
                    dict(type=kind, state="blocked", reason="probe_run_key_already_used")
                )
                break
            job = repo.claim(queued["job_id"])
            if not job:
                raise AppError("probe_job_unavailable", "Probe job cannot be claimed", 409)
            context = ExecutionContext(
                repo, job["job_id"], job["lease_token"], job["deadline_at"], settings
            )
            sources = [Source.model_validate(s) for s in job["payload"]["sources"]]
            started = time.monotonic()

            async def heartbeat(context=context):
                while True:
                    await asyncio.sleep(settings.job_lease_seconds / 3)
                    repo.heartbeat(context.job_id, context.lease_token)

            pulse = asyncio.create_task(heartbeat())
            try:
                async with asyncio.timeout(context.remaining_seconds):
                    value = ArtifactResult.model_validate(
                        await runtime.artifact(request, sources, context)
                    )
                    value = await validate_result(value, sources, runtime, context, full_task=True)
                repo.finish(job["job_id"], job["lease_token"], value.model_dump(mode="json"))
                saved = repo.get_job(job["job_id"])
                artifact_ids = saved["result"]["artifact_ids"]
                reread = [repo.artifact(aid) for aid in artifact_ids]
                if not reread or any(
                    artifact["content"] != value.content.model_dump(mode="json")
                    or artifact["citations"] != [c.model_dump(mode="json") for c in value.citations]
                    or not artifact["sources_available"]
                    for artifact in reread
                ):
                    raise AppError(
                        "probe_history_mismatch", "Stored artifact did not match publication", 502
                    )
                results.append(
                    dict(
                        type=kind,
                        state="completed",
                        contract_verified=bool(reread),
                        human_quality_review="pending",
                        model=value.provider_metadata.returned_model,
                        usage=value.provider_metadata.usage,
                        citation_kinds=sorted({c.kind for c in value.citations}),
                        artifact_ids=artifact_ids,
                        source_versions=[s.model_dump() for s in sources],
                        total_ms=(time.monotonic() - started) * 1000,
                    )
                )
            except AppError as exc:
                stop_owned(repo, job, exc)
                # The probe has no automatic retries; stop queued retry work explicitly.
                results.append(dict(type=kind, state="blocked", reason=exc.code))
                break
            except Exception:
                stop_owned(
                    repo,
                    job,
                    AppError("probe_failed", "Probe did not complete", 503),
                )
                results.append(dict(type=kind, state="blocked", reason="probe_failed"))
                break
            finally:
                pulse.cancel()
                with suppress(asyncio.CancelledError):
                    await pulse
    finally:
        actor_id.reset(token)
        await runtime.close()
        database.close()
    return dict(
        live=True,
        semantic_quality_verified=False,
        results=results,
        attempted_calls=budget.calls,
        reserved_probe_tokens=budget.tokens,
        dispatched_roundtrip_ms=budget.provider_ms,
        stage_timing_note=(
            "Dispatch-to-settlement time includes SDK handling. "
            "Queue/retrieval stages were not separately measured."
        ),
        model=settings.llm_model,
        embedding_model=config["rag"].embedding_model,
    )


def implementation_fingerprints():
    import importlib

    result = {}
    for package in (
        "youtube_backend",
        "youtube_rag",
        "youtube_agent",
        "youtube_answers",
        "youtube_ingestion",
    ):
        root = Path(importlib.import_module(package).__file__).parent
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*.py")):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
        result[package] = digest.hexdigest()
    return result


def main():
    from youtube_backend.full import FullSettings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--run-key", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        settings = FullSettings(_env_file=args.env_file)
        # Export full resolution before a factory can read module-local dotenv files.
        import os

        os.environ.update(settings.child_environment())
        budget = ProbeBudget(args.max_calls, args.max_tokens)
        with budget.bind():
            result = asyncio.run(
                probe(
                    settings,
                    owner=args.owner,
                    video_id=args.video_id,
                    topic=args.topic,
                    budget=budget,
                    types=("quiz", "flashcards", "study_plan"),
                    run_key=args.run_key or uuid4().hex,
                )
            )
        result["implementation_sha256"] = implementation_fingerprints()
    except Exception as exc:
        # No raw config/provider exception or credential/identity in the report.
        result = dict(
            live=True,
            semantic_quality_verified=False,
            results=[
                dict(
                    state="blocked",
                    reason=exc.code
                    if isinstance(exc, AppError)
                    else "configuration_or_probe_failed",
                )
            ],
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result))
    raise SystemExit(
        0
        if len(result["results"]) == 3 and all(r["state"] == "completed" for r in result["results"])
        else 2
    )


if __name__ == "__main__":
    main()
