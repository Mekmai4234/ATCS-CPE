"""Explicit live YouTube -> real 02/04 storage check, using labelled fixture vectors."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.urls import VIDEO_ID
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import initialize

from youtube_ingestion.captions import SubprocessCaptions
from youtube_ingestion.config import IngestionSettings
from youtube_ingestion.integration import IngestionAdapters
from youtube_ingestion.service import IngestionService


class RecordedCaptions(SubprocessCaptions):
    def __init__(self):
        super().__init__()
        self.timings = {}
        self.calls = {}

    async def fetch(self, video_id, languages, timeout):
        self.calls[video_id] = self.calls.get(video_id, 0) + 1
        value = await super().fetch(video_id, languages, timeout)
        self.timings[video_id] = [
            (s["start"], s["duration"])
            for s in sorted(value["segments"], key=lambda s: s["start"])
            if s["text"].strip()
        ]
        return value


async def check(state, video_ids):
    # A unique, initially empty directory is required: never migrate an existing app DB.
    if state.exists() and any(state.iterdir()):
        raise ValueError("Use a new empty acceptance state directory")
    state.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        app_env="test",
        adapter_mode="custom",
        # Deliberately distinct identity, unusable by the production live factory.
        adapter_factory="acceptance_only:live_captions_fixture_vectors",
        backend_integration_profile="offline",
        database_url=f"sqlite:///{(state / 'app.db').as_posix()}",
        job_timeout_seconds=120,
        job_lease_seconds=30,
    )
    database = Database(settings.database_url)
    knowledge, ingestion = None, None
    started = time.monotonic()
    report = dict(
        mode="live-youtube-with-fixture-embeddings",
        embedding_provider="fixture",
        semantic_quality_evaluated=False,
        gemini_called=False,
        cases=[],
    )
    try:
        upgrade_database(database)
        initialize(database)
        rag_config = RagSettings(
            _env_file=None,
            embedding_provider="fixture",
            embedding_model="fixture-hash-v1",
            embedding_dimensions=64,
            chroma_persist_dir=state / "chroma",
        )
        knowledge = RagAdapters(
            settings=settings,
            repository=Repository(database, settings),
            rag_settings=rag_config,
            embedder=FixtureEmbedder(rag_config),
        )
        captions = RecordedCaptions()
        ingestion = IngestionService(
            IngestionSettings(
                _env_file=None, metadata_provider="oembed", transcript_languages="th,en"
            ),
            captions=captions,
        )
        app = create_app(settings, database, IngestionAdapters(ingestion, knowledge))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                for video_id in video_ids:
                    case_start = time.monotonic()
                    body = {"urls": [f"https://youtu.be/{video_id}"]}
                    response = await client.post("/api/videos/import", json=body)
                    response.raise_for_status()
                    job_id = response.json()["jobs"][0]["job_id"]
                    await app.state.worker.run_once(job_id)
                    job = app.state.repository.get_job(job_id)
                    case = dict(
                        video_id=video_id,
                        stage=job["stage"],
                        error_code=job["error_code"],
                        retryable=job["retryable"],
                    )
                    if job["stage"] == "ready":
                        segments, offset = [], 0
                        while True:
                            page = app.state.repository.transcript(video_id, 200, offset)
                            segments.extend(page["segments"])
                            offset += len(page["segments"])
                            if offset >= page["total"]:
                                break
                        duplicate = await client.post(
                            "/api/videos/import",
                            json={"urls": [f"https://www.youtube.com/watch?v={video_id}"]},
                        )
                        duplicate.raise_for_status()
                        item = duplicate.json()["jobs"][0]
                        case.update(
                            language=page["language"],
                            segment_count=len(segments),
                            timestamps_match_provider=[
                                (s["start_seconds"], s["duration_seconds"]) for s in segments
                            ]
                            == captions.timings[video_id],
                            chunk_count=job["result"]["chunk_count"],
                            duplicate_reuses_job=item["job_id"] == job_id
                            and item["outcome"] == "existing",
                            caption_fetches=captions.calls[video_id],
                        )
                    case["passed"] = bool(
                        case.get("timestamps_match_provider")
                        and case.get("duplicate_reuses_job")
                        and case.get("caption_fetches") == 1
                    )
                    case["latency_seconds"] = round(time.monotonic() - case_start, 3)
                    report["cases"].append(case)
        report["passed"] = bool(report["cases"]) and all(c["passed"] for c in report["cases"])
    finally:
        try:
            if ingestion is not None:
                await ingestion.close()
        finally:
            try:
                if knowledge is not None:
                    await knowledge.close()
            finally:
                database.close()
    report["latency_seconds"] = round(time.monotonic() - started, 3)
    (state / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--video-id", required=True, action="append")
    parser.add_argument(
        "--fixture-embeddings",
        required=True,
        action="store_true",
        help="Explicitly acknowledge that vector values are test doubles",
    )
    args = parser.parse_args()
    if any(not VIDEO_ID.fullmatch(video_id) for video_id in args.video_id):
        parser.error("Use valid 11-character video IDs")
    try:
        result = asyncio.run(check(args.state.resolve(), args.video_id))
    except Exception as error:
        # Never print raw provider exceptions or a configured key.
        result = dict(passed=False, error_code=getattr(error, "code", type(error).__name__))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
