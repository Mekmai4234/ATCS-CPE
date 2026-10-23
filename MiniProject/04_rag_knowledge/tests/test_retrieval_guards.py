import base64
import json
from types import SimpleNamespace

import pytest
from conftest import VIDEO_A
from youtube_backend.errors import AppError

from youtube_rag.authorization import authenticated


@pytest.mark.parametrize(
    "settings",
    [
        SimpleNamespace(app_env="production", auth_enabled=False),
        SimpleNamespace(app_env="development"),
    ],
)
def test_missing_or_disabled_production_authorization_fails_closed(settings):
    with pytest.raises(AppError):
        authenticated(settings)


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "video_id",
        "generation",
        "transcript_version",
        "start_seconds",
        "vector_id",
        "distance",
    ],
)
async def test_forged_vector_candidate_never_returns_evidence(env, monkeypatch, field):
    await env.ready()
    task = env.query(VIDEO_A)
    original = env.rag.vectors.call

    async def forged(command, *args, **kwargs):
        response = await original(command, *args, **kwargs)
        if command == "query":
            if field == "vector_id":
                response["ids"][0][0] = "foreign:chunk"
            elif field == "distance":
                response["distances"][0][0] = float("nan")
            else:
                response["metadatas"][0][0][field] = "foreign-value"
        return response

    monkeypatch.setattr(env.rag.vectors, "call", forged)
    with pytest.raises(AppError) as caught:
        await env.rag.search("Embeddings", task.sources, task.execution)
    assert caught.value.code == "incomplete_index"


@pytest.mark.parametrize("kind", ["unsigned", "offset", "signature"])
async def test_cursor_tampering_is_rejected(env, kind):
    await env.ready()
    task = env.query(VIDEO_A)
    page = await env.rag.read_video_chunks(task.sources, task.execution, limit=1)
    raw = bytearray(base64.urlsafe_b64decode(page.next_cursor))
    if kind == "signature":
        raw[0] ^= 1
    elif kind == "offset":
        value = json.loads(raw[32:])
        value["offset"] += 1
        raw = raw[:32] + json.dumps(value).encode()
    else:
        raw = json.dumps({"snapshot": "forged", "offset": 0}).encode()
    cursor = base64.urlsafe_b64encode(raw).decode()
    with pytest.raises(AppError) as caught:
        await env.rag.read_video_chunks(task.sources, task.execution, cursor=cursor)
    assert caught.value.code == "invalid_cursor"
