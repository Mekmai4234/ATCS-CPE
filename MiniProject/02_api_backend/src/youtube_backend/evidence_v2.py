"""Versioned media handoff. Source/transcript/citation v1 stays unchanged."""

from typing import Literal

from pydantic import Field, model_validator

from .schemas import Schema


class SourceSnapshotV2(Schema):
    contract_version: Literal[2] = 2
    video_id: str = Field(pattern=r"^[\w-]{11}$")
    generation: int = Field(ge=1)
    kind: Literal["transcript", "ocr", "visual"]
    evidence_version: str = Field(pattern=r"^[a-f0-9]{64}$")

    @classmethod
    def from_transcript(cls, source):
        return cls(
            video_id=source.video_id,
            generation=source.generation,
            kind="transcript",
            evidence_version=source.transcript_version,
        )


class FrameInput(Schema):
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    content: bytes = Field(min_length=8, exclude=True)
    mime: Literal["image/png", "image/jpeg", "image/webp"]
    ocr_text: str = Field(default="", max_length=20000)
    visual_text: str = Field(default="", max_length=20000)


class MediaEnrichment(Schema):
    sampling_version: str = Field(min_length=1, max_length=100)
    ocr_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_seconds: float = Field(gt=0, le=600, allow_inf_nan=False)
    frames: list[FrameInput] = Field(min_length=1, max_length=100)
    whole_video_reviewed: Literal[False] = False
    vision_reservation_id: str | None = None
    requested_model: str | None = None
    returned_model: str | None = None
    vision_input_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def sampled_times(self):
        times = [f.timestamp_seconds for f in self.frames]
        if times != sorted(set(times)) or times[-1] > self.duration_seconds:
            raise ValueError("Frames must have ordered distinct timestamps inside the video")
        if any(f.visual_text.strip() for f in self.frames) and not all(
            (
                self.vision_reservation_id,
                self.requested_model,
                self.returned_model,
                self.vision_input_hash,
            )
        ):
            raise ValueError("Visual observations require model/request/broker provenance")
        return self


class VisualCitationV2(Schema):
    contract_version: Literal[2] = 2
    source: SourceSnapshotV2
    frame_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    asset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=20000)
    asset_url: str

    @model_validator(mode="after")
    def exact_asset_route(self):
        if (
            self.source.kind == "transcript"
            or self.asset_url != f"/api/media/assets/{self.asset_id}"
        ):
            raise ValueError(
                "Visual evidence requires an OCR/visual snapshot and authorized asset route"
            )
        return self
