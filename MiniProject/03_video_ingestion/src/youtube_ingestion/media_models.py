"""03 internal handoff DTOs, not 02's not-yet-agreed public evidence contract."""

from typing import Literal

from pydantic import Field
from youtube_backend.schemas import Schema


class MediaInfo(Schema):
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    start_time_seconds: float = Field(default=0, allow_inf_nan=False)
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    video_stream_index: int = Field(ge=0)
    fps: float = Field(gt=0, le=1000, allow_inf_nan=False)
    has_audio: bool
    has_subtitle_stream: bool


class OcrWord(Schema):
    text: str = Field(max_length=2000)
    confidence: float = Field(ge=0, le=100, allow_inf_nan=False)
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class OcrResult(Schema):
    kind: Literal["ocr"] = "ocr"
    engine: Literal["tesseract"] = "tesseract"
    engine_version: str | None = None
    fingerprint: str
    languages: str
    status: Literal["ready", "empty", "unavailable"]
    text: str = Field(default="", max_length=20000)
    words: list[OcrWord] = Field(default_factory=list, max_length=10000)
    reason: str | None = None


class MediaFrame(Schema):
    frame_id: str
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    seek_timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    timestamp_basis: Literal["decoded_stream_pts"] = "decoded_stream_pts"
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    # Private server asset key. 02 must resolve it through an authorized image API.
    asset_key: str
    perceptual_hash: str = Field(pattern=r"^[a-f0-9]{22}$")
    near_duplicate_of: str | None = None
    selected_for_vision: bool = True
    ocr: OcrResult


class SamplingCoverage(Schema):
    strategy: Literal["uniform_midpoints_v1"] = "uniform_midpoints_v1"
    sampled_timestamps: list[float]
    inspected_intervals: list[tuple[float, float]]
    unsampled_intervals: list[tuple[float, float]]
    whole_video_reviewed: Literal[False] = False
    limitations: str = "Sampled still frames only; brief events between samples may be missed."


class PreparedMedia(Schema):
    kind: Literal["media"] = "media"
    schema_version: Literal["03-local-v1"] = "03-local-v1"
    media_version: str
    source_sha256: str
    extraction_engine: str
    info: MediaInfo
    frames: list[MediaFrame]
    coverage: SamplingCoverage
    stored_image_bytes: int = Field(ge=0)
    visual_analysis: Literal["not_requested"] = "not_requested"
