"""Bounded public YouTube inputs; never accept arbitrary URLs from model output."""

import re
from dataclasses import dataclass

from youtube_backend.errors import AppError
from youtube_backend.schemas import Source
from youtube_backend.urls import canonical_url


@dataclass(frozen=True)
class VideoPlan:
    source: Source
    start_seconds: float = 0
    end_seconds: float | None = None
    fps: float = 0.25

    @classmethod
    def from_question(cls, source, question):
        """Parse whole clock tokens, never a prefix of an hours timestamp."""
        matches = list(re.finditer(r"(?<![\d:])[\d:]*\d:[\d:]+(?![\d:])", question))
        if not matches:
            return cls(source)
        if len(matches) > 2:
            raise AppError("ambiguous_video_time", "Use one time or one continuous range", 422)
        if re.search(r"[-−]\s*$", question[: matches[0].start()]):
            raise AppError("invalid_video_time", "Negative video timestamps are invalid", 422)
        seconds = []
        for match in matches:
            parts = match.group().split(":")
            if (
                len(parts) not in {2, 3}
                or any(not part.isdecimal() for part in parts)
                or len(parts[0]) > (2 if len(parts) == 3 else 3)
                or len(parts[-1]) != 2
                or (len(parts) == 3 and len(parts[-2]) != 2)
                or int(parts[-1]) >= 60
                or (len(parts) == 3 and int(parts[-2]) >= 60)
            ):
                raise AppError("invalid_video_time", "Use MM:SS or HH:MM:SS", 422)
            value = 0
            for part in parts:
                value = value * 60 + int(part)
            if value > 7200:
                raise AppError(
                    "video_time_out_of_bounds", "Video inspection is limited to two hours", 422
                )
            seconds.append(value)
        if len(seconds) == 1:
            start = min(max(0, seconds[0] - 5), 7180)
            return cls(source, start, min(seconds[0] + 15, 7200), 3)
        connector = question[matches[0].end() : matches[1].start()]
        if not re.fullmatch(
            r"\s*(?:นาที|น\.)?\s*(?:[-–—]|ถึง|จนถึง|to|until|through)\s*", connector, re.I
        ):
            raise AppError("ambiguous_video_time", "Specify one continuous time range", 422)
        start, end = seconds
        if start >= end:
            raise AppError("invalid_video_time_range", "Range end must be after its start", 422)
        return cls(source, start, end, 3 if end - start <= 20 else 0.25)

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", self.source.video_id):
            raise ValueError("A canonical YouTube video ID is required")
        if (
            not 0 <= self.start_seconds < (self.end_seconds or 7200) <= 7200
            or not 0 < self.fps <= 3
        ):
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
                end_offset=f"{self.end_seconds}s" if self.end_seconds else None,
                fps=self.fps,
            ),
        )

    def focus(self, start, end):
        if end - start > 20 or start < self.start_seconds or end > (self.end_seconds or 7200):
            raise ValueError("Focused inspection must stay inside the selected clip window")
        return VideoPlan(self.source, start, end, 3)
