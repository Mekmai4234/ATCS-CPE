from requests import ConnectionError, HTTPError, Timeout
from youtube_backend.errors import AppError
from youtube_transcript_api import (
    AgeRestricted,
    InvalidVideoId,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeRequestFailed,
)


def failure(code, message, status=502, retryable=False):
    return AppError(code, message, status, retryable)


def classify(exc):
    """Do not expose provider exception messages (URLs, credentials or upstream text)."""
    if isinstance(exc, (NoTranscriptFound, TranscriptsDisabled)):
        return failure("no_transcript", "No usable captions in the requested languages", 409)
    if isinstance(exc, InvalidVideoId):
        return failure("invalid_video_id", "Provide a valid YouTube video ID", 422)
    if isinstance(exc, AgeRestricted):
        return failure(
            "video_restricted", "Captions require access not supported by this adapter", 403
        )
    if isinstance(exc, (VideoUnavailable, VideoUnplayable)):
        return failure("video_unavailable", "Video is unavailable or unplayable", 404)
    if isinstance(exc, RequestBlocked):
        # This includes IpBlocked. Repeating requests does not fix an IP/access block.
        return failure(
            "youtube_access_blocked", "YouTube blocked access from this environment", 503
        )
    if isinstance(exc, Timeout):
        return failure("ingest_timeout", "Caption request exceeded its deadline", 504, True)
    if isinstance(exc, ConnectionError):
        return failure("ingest_unavailable", "Caption transport is unavailable", 503, True)
    if isinstance(exc, (YouTubeRequestFailed, HTTPError)):
        # The library wraps HTTPError; inspect structured status, never parse its message.
        current = exc
        while current is not None:
            status = getattr(getattr(current, "response", None), "status_code", None)
            if isinstance(status, int):
                transient = status in {408, 429} or status >= 500
                return failure(
                    "youtube_rate_limited"
                    if status == 429
                    else "caption_provider_transient"
                    if transient
                    else "caption_provider_error",
                    "YouTube rejected the caption request",
                    503 if transient else 502,
                    transient,
                )
            current = current.__cause__ or current.__context__
        return failure("caption_provider_error", "YouTube rejected the caption request")
    return failure("caption_provider_error", "Caption provider returned an unsupported response")
