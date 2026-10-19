"""Explicit public YouTube read, no database writes and no embeddings/generation calls."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from youtube_backend.errors import AppError

from youtube_ingestion.config import IngestionSettings
from youtube_ingestion.service import IngestionService


class Deadline:
    def __init__(self, seconds):
        self.end = time.monotonic() + seconds

    @property
    def remaining_seconds(self):
        return max(0, self.end - time.monotonic())

    def check(self):
        if self.remaining_seconds <= 0:
            raise AppError("task_timeout", "Live check deadline reached", 504)


async def check(video_id):
    settings = IngestionSettings()
    service = IngestionService(settings)
    started = time.monotonic()
    result = dict(
        video_id=video_id,
        mode="live-youtube",
        database_written=False,
        embeddings_called=False,
        generation_called=False,
    )
    try:
        transcript = await service.ingest(video_id, Deadline(settings.ingest_timeout_seconds + 1))
        result.update(
            passed=True,
            language=transcript.language,
            source=transcript.source,
            segment_count=len(transcript.segments),
            metadata_available=transcript.title is not None,
            first_start_seconds=transcript.segments[0].start_seconds,
            last_end_seconds=max(s.start_seconds + s.duration_seconds for s in transcript.segments),
        )
    except AppError as error:
        result.update(passed=False, error_code=error.code, retryable=error.retryable)
    except Exception:
        result.update(passed=False, error_code="unexpected_check_failure", retryable=False)
    finally:
        await service.close()
    result["latency_seconds"] = round(time.monotonic() - started, 3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(check(args.video_id))
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(encoded)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
