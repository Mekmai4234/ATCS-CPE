"""Measure local retrieval for first, repeated and DIFFERENT questions; no provider calls."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from evidence_review import latency_summary
from learning_probe import implementation_fingerprints


async def measure(search, questions):
    if not 2 <= len(questions) <= 50 or len(set(questions)) != len(questions):
        raise ValueError("Use 2–50 genuinely distinct questions")
    samples = []
    planned = [("first_question", questions[0])]
    planned += [("same_question", questions[0])] * 20
    planned += [("new_question_same_clip", question) for question in questions[1:]]
    for scenario, question in planned:
        started = time.perf_counter()
        result = await search(question)
        elapsed = (time.perf_counter() - started) * 1000
        samples.append(
            dict(
                scenario=scenario,
                mode="local_library",
                duration_class="unknown",
                retrieval_ms=elapsed,
                queue_ms=None,
                provider_ms=0,
                total_ms=elapsed,
                evidence_hits=len(result.items),
                collection_complete=result.complete,
            )
        )
    return dict(
        measurement_scope="local_retrieval_only_not_answer_latency",
        provider_calls=0,
        samples=samples,
        summary=latency_summary(samples),
        semantic_quality_verified=False,
        notes=[
            "Different question strings do not prove semantic relevance. "
            "Review evidence hits separately."
        ],
    )


async def run(settings, owner, video, questions):
    from youtube_backend.auth import actor_id
    from youtube_backend.database import Database
    from youtube_backend.integrations import ExecutionContext
    from youtube_backend.quota import QuotaBroker
    from youtube_backend.repository import Repository
    from youtube_backend.runtime import ManagedAdapters
    from youtube_backend.schemas import Source

    database = Database(settings.database_url)
    repo = Repository(database, settings)
    runtime = ManagedAdapters(settings, repo)
    token = actor_id.set(owner)
    job = None
    try:
        with patch.object(
            QuotaBroker,
            "reserve",
            side_effect=AssertionError("Benchmark forbids provider admission"),
        ):
            await runtime.start()
            queued = repo.enqueue(
                "research",
                dict(goal="[LOCAL BENCHMARK] Retrieval only", scope={"video_ids": [video]}),
            )
            job = repo.claim(queued["job_id"])
            if not job:
                raise ValueError("Benchmark lease unavailable")
            context = ExecutionContext(
                repo, job["job_id"], job["lease_token"], job["deadline_at"], settings
            )
            sources = [Source.model_validate(s) for s in job["payload"]["sources"]]
            library = runtime.adapter.answers.rag.evidence_library()

            async def search(question):
                return await library.search(
                    question, sources, context, kinds=["transcript"], limit=8
                )

            result = await measure(search, questions)
            result["source_versions"] = [s.model_dump() for s in sources]
            result["implementation_sha256"] = implementation_fingerprints()
            return result
    finally:
        if job:
            repo.cancel(job["job_id"])
            from youtube_backend.errors import AppError

            repo.fail(
                job["job_id"],
                job["lease_token"],
                AppError("cancelled", "Local benchmark finished", 409),
            )
        actor_id.reset(token)
        await runtime.close()
        database.close()


def main():
    from youtube_backend.full import FullSettings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-state-probe", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        settings = FullSettings(_env_file=args.env_file)
        os.environ.update(settings.child_environment())
        result = asyncio.run(
            run(settings, args.owner, args.video_id, json.loads(args.questions.read_text("utf-8")))
        )
    except Exception:
        parser.exit(
            2, "Local benchmark blocked; check configuration, source grants and question file.\n"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"samples", "source_versions", "implementation_sha256"}
            }
        )
    )


if __name__ == "__main__":
    main()
