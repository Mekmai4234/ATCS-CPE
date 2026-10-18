import time

import pytest
from youtube_backend.errors import AppError

from youtube_ingestion.config import IngestionSettings

VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "jNQXAC9IVRw"


def track(video_id=VIDEO_A, **updates):
    data = dict(
        video_id=video_id,
        language="th",
        is_generated=False,
        segments=[
            {"text": " RAG   ค้นหลักฐานก่อนตอบ ", "start": 0.0, "duration": 12.0},
            {"text": "Embeddings represent text as vectors", "start": 12.0, "duration": 10.0},
        ],
    )
    return dict(data, **updates)


class Context:
    def __init__(self, seconds=30):
        self.deadline = time.monotonic() + seconds
        self.cancelled = False

    @property
    def remaining_seconds(self):
        return max(0, self.deadline - time.monotonic())

    def check(self):
        if self.cancelled:
            raise AppError("cancelled", "Task cancelled", 409)
        if self.remaining_seconds <= 0:
            raise AppError("task_timeout", "Task exceeded deadline", 504, True)


@pytest.fixture
def config():
    return IngestionSettings(_env_file=None, metadata_provider="none")
