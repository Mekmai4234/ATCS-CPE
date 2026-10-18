import hashlib
import json

from pydantic import ValidationError
from youtube_backend.schemas import Segment, TranscriptResult

from .errors import failure
from .models import CaptionTrack, Metadata


def normalize(video_id, track, metadata=None):
    try:
        track = CaptionTrack.model_validate(track)
        metadata = Metadata.model_validate(metadata or {})
        if track.video_id != video_id:
            raise ValueError("Mismatched video")
        segments, occurrences = [], {}
        for raw in sorted(track.segments, key=lambda s: s.start):
            text = " ".join(raw.text.split())
            if not text:
                continue
            identity = json.dumps(
                [track.language, text, raw.start, raw.duration],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            digest = hashlib.sha256(identity).hexdigest()
            occurrence = occurrences.get(digest, 0)
            occurrences[digest] = occurrence + 1
            segments.append(
                Segment(
                    segment_id=f"yt-{digest}-{occurrence}",
                    text=text,
                    start_seconds=raw.start,
                    duration_seconds=raw.duration,
                )
            )
        if not segments:
            raise failure("no_transcript", "Caption track contains no usable text", 409)
        return TranscriptResult(
            video_id=video_id,
            language=track.language,
            source="youtube_captions:generated"
            if track.is_generated
            else "youtube_captions:manual",
            segments=segments,
            **metadata.model_dump(),
        )
    except (ValidationError, ValueError, TypeError):
        raise failure(
            "invalid_transcript", "Caption data contains invalid fields or intervals"
        ) from None
