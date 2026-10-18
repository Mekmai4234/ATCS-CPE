import json
import re
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError
from youtube_backend.urls import canonical_url

from .errors import failure
from .models import Metadata


class YouTubeMetadata:
    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(follow_redirects=False)
        self.owns_client = client is None

    async def fetch(self, video_id, timeout):
        provider = self.settings.metadata_provider
        if provider == "none":
            return Metadata()
        if provider == "auto":
            provider = (
                "youtube_api" if self.settings.youtube_api_key.get_secret_value() else "oembed"
            )
        if provider == "youtube_api":
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {"part": "snippet", "id": video_id}
            # Keep the API key out of request URLs and HTTPX's ordinary request logs.
            headers = {"X-Goog-Api-Key": self.settings.youtube_api_key.get_secret_value()}
        else:
            url = "https://www.youtube.com/oembed"
            params = {"url": canonical_url(video_id), "format": "json"}
            headers = {}
        try:
            async with self.client.stream(
                "GET", url, params=params, headers=headers, timeout=timeout, follow_redirects=False
            ) as response:
                if response.status_code != 200:
                    raise failure("metadata_unavailable", "Video metadata is unavailable", 503)
                data, count = [], 0
                async for chunk in response.aiter_bytes():
                    count += len(chunk)
                    if count > 1024 * 1024:
                        raise ValueError("Metadata too large")
                    data.append(chunk)
            payload = json.loads(b"".join(data))
            if provider == "youtube_api":
                item = payload["items"][0]
                if item["id"] != video_id:
                    raise ValueError("Mismatched video")
                snippet = item["snippet"]
                thumbnails = snippet.get("thumbnails", {})
                thumbnail = next(
                    (
                        thumbnails[k]["url"]
                        for k in ("high", "medium", "default")
                        if k in thumbnails
                    ),
                    None,
                )
                published = snippet.get("publishedAt")
                timestamp = (
                    datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
                )
                if timestamp is not None and timestamp.tzinfo is None:
                    raise ValueError("Missing publication timezone")
                result = Metadata(
                    title=snippet.get("title"),
                    channel_id=snippet.get("channelId"),
                    channel_title=snippet.get("channelTitle"),
                    thumbnail_url=thumbnail,
                    published_at=timestamp.astimezone(UTC).date() if timestamp else None,
                )
            else:
                # Handles and channel names do not imply a stable YouTube channel ID.
                author_url = payload.get("author_url", "")
                match = re.fullmatch(
                    r"https://www\.youtube\.com/channel/(UC[\w-]{22})/?", author_url
                )
                result = Metadata(
                    title=payload.get("title"),
                    channel_title=payload.get("author_name"),
                    channel_id=match.group(1) if match else None,
                    thumbnail_url=payload.get("thumbnail_url"),
                )
            if result.thumbnail_url and not result.thumbnail_url.startswith("https://"):
                raise ValueError("Invalid thumbnail scheme")
            return result
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            ValidationError,
        ):
            raise failure("metadata_unavailable", "Video metadata is unavailable", 503) from None

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
