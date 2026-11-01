from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from conftest import metadata, source
from youtube_backend.errors import AppError

from youtube_answers.companion import reply
from youtube_answers.models import Generated


async def test_companion_is_bounded_and_never_claims_video_evidence():
    calls = []

    async def generate(payload, timeout, **kwargs):
        calls.append((payload, kwargs))
        return Generated(kwargs["schema"](answer="Buddy คุยเป็นเพื่อนได้ครับ"), metadata())

    model = SimpleNamespace(
        generate=generate, broker=SimpleNamespace(bind=lambda context: nullcontext())
    )
    job = {"kind": "chat", "payload": {"request": {"mode": "general"}}}
    context = SimpleNamespace(
        check=lambda: None,
        remaining_seconds=60,
        job_id="job",
        lease_token="lease",
        repository=SimpleNamespace(check_execution=lambda *args: job),
    )
    adapter = SimpleNamespace(answers=SimpleNamespace(model=model))
    result = await reply(
        adapter, {"question": "ทำอะไรดี"}, [], [{"role": "user", "content": "x" * 7000}], context
    )
    assert result.citations == [] and result.coverage.expected_videos == 0
    assert calls[0][0]["history"] == [] and calls[0][1]["output_limit"] == 1024
    assert "NOT inspected any video" in calls[0][1]["policy"]
    with pytest.raises(AppError):
        await reply(adapter, {"question": "clip"}, [source()], [], context)
    job["payload"]["request"]["mode"] = "video"
    with pytest.raises(AppError):
        await reply(adapter, {"question": "clip"}, [], [], context)
    assert len(calls) == 1
