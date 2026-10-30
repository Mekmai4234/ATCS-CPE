"""Bounded public YouTube inputs; never accept arbitrary URLs from model output."""

from dataclasses import dataclass

from youtube_backend.schemas import Source
from youtube_backend.urls import canonical_url


@dataclass(frozen=True)
class VideoPlan:
    source: Source
    start_seconds: float = 0
    end_seconds: float | None = None
    fps: float = 0.25

    def __post_init__(self):
        if not 0 <= self.start_seconds < (self.end_seconds or 7200) <= 7200 or not 0 < self.fps <= 3:
            raise ValueError("Video windows must stay within the bounded inspection range")

    @property
    def uri(self):
        return canonical_url(self.source.video_id)

    def part(self):
        from google.genai import types

        return types.Part(
            file_data=types.FileData(file_uri=self.uri, mime_type="video/mp4"),
            video_metadata=types.VideoMetadata(
                start_offset=f"{self.start_seconds}s",
                end_offset=f"{self.end_seconds}s" if self.end_seconds else None, fps=self.fps,
            ),
        )

    def focus(self, start, end):
        if end - start > 20 or start < self.start_seconds or end > (self.end_seconds or 7200):
            raise ValueError("Focused inspection must stay inside the selected clip window")
        return VideoPlan(self.source, start, end, 3)
