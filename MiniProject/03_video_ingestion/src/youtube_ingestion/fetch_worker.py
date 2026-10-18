"""Private one-shot process for the synchronous caption SDK. No application persistence."""

import json
import sys

from requests import Session
from requests.adapters import HTTPAdapter
from youtube_backend.urls import VIDEO_ID
from youtube_transcript_api import YouTubeTranscriptApi

from .errors import classify


class BoundedSession(Session):
    def __init__(self, timeout):
        super().__init__()
        self.request_timeout = timeout
        self.mount("https://", HTTPAdapter(max_retries=0))

    def request(self, *args, **kwargs):
        kwargs["timeout"] = self.request_timeout
        response = super().request(*args, **kwargs)
        # SDK 1.2 maps every HTTP 429 to IpBlocked, losing the transport distinction.
        # Preserve explicit HTTP rate limits for 02's bounded backoff. A bot/access
        # rejection reported by YouTube's player still becomes RequestBlocked.
        if response.status_code == 429:
            response.raise_for_status()
        return response


def fetch(video_id, languages, timeout):
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Invalid video ID")
    with BoundedSession(timeout) as session:
        # SDK find_transcript prefers all manual languages over all generated ones.
        # Our policy is language priority FIRST, then manual within that language.
        tracks = list(YouTubeTranscriptApi(http_client=session).list(video_id))
        selected = next(
            (
                track
                for language in languages
                for generated in (False, True)
                for track in tracks
                if track.language_code == language and track.is_generated == generated
            ),
            None,
        )
        if selected is None:
            return {"ok": False, "code": "no_transcript"}
        transcript = selected.fetch(preserve_formatting=False)
        return {
            "ok": True,
            "track": {
                "video_id": video_id,
                "language": selected.language_code,
                "is_generated": selected.is_generated,
                "segments": transcript.to_raw_data(),
            },
        }


def main():
    try:
        request = json.loads(sys.stdin.buffer.readline(8192))
        response = fetch(request["video_id"], request["languages"], request["timeout"])
    except Exception as exc:
        response = {"ok": False, "code": classify(exc).code}
    # ASCII JSON survives Windows console encodings and preserves Unicode on decoding.
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
