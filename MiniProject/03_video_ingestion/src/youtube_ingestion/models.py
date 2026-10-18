from datetime import date

from pydantic import Field
from youtube_backend.schemas import Schema


class RawSegment(Schema):
    text: str
    start: float = Field(ge=0, strict=True)
    duration: float = Field(gt=0, strict=True)


class CaptionTrack(Schema):
    video_id: str
    language: str = Field(min_length=1, max_length=30)
    is_generated: bool = Field(strict=True)
    segments: list[RawSegment] = Field(max_length=100000)


class Metadata(Schema):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    channel_id: str | None = Field(default=None, min_length=1, max_length=200)
    channel_title: str | None = Field(default=None, min_length=1, max_length=1000)
    thumbnail_url: str | None = Field(default=None, max_length=2048)
    published_at: date | None = None
