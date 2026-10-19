import re
from urllib.parse import parse_qs, urlsplit

from .errors import AppError

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def normalize_url(value: str) -> str:
    """Pure parsing: never perform a request to the user-provided URL."""
    try:
        if len(value) > 2048:
            raise ValueError
        url = urlsplit(value.strip())
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            raise ValueError
        host = (url.hostname or "").lower()
        if host == "youtu.be":
            video_id = url.path.removeprefix("/")
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if url.path != "/watch":
                raise ValueError
            values = parse_qs(url.query).get("v", [])
            if len(values) != 1:
                raise ValueError
            video_id = values[0]
        else:
            raise ValueError
        if not VIDEO_ID.fullmatch(video_id):
            raise ValueError
        return video_id
    except ValueError:
        raise AppError(
            "invalid_youtube_url", "Use an HTTPS YouTube watch or youtu.be URL"
        ) from None


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"
