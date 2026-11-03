from types import SimpleNamespace

import pytest
from youtube_backend.schemas import AnswerResult, Coverage, ProviderMetadata

from youtube_answers.config import AnswerSettings
from youtube_answers.gemini import GeminiModel
from youtube_answers.integration import AnswerAdapters
from youtube_answers.models import error


def transcript_answer():
    return AnswerResult(
        status="answered",
        answer="[FIXTURE] answered from the transcript",
        citations=[],
        coverage=Coverage(expected_videos=1, processed_videos=1),
        provider_metadata=ProviderMetadata(
            provider="gemini",
            requested_model="gemini-3.5-flash-lite",
            latency_ms=1,
            fallback_from="gemini-3.5-flash",
        ),
    )


def adapters(monkeypatch, native_error, answer):
    import youtube_answers.video as video

    class Native:
        def __init__(self, model, settings):
            pass

        async def answer(self, *args, **kwargs):
            raise native_error

    monkeypatch.setattr(video, "NativeVideoAnswers", Native)
    settings = AnswerSettings(_env_file=None)
    team = AnswerAdapters.__new__(AnswerAdapters)
    team.answers = SimpleNamespace(
        model=GeminiModel(settings, client=object(), broker=None),
        settings=settings,
        answer=answer,
    )
    return team


@pytest.mark.parametrize(
    "code",
    ["quota_wait", "provider_unavailable", "provider_rate_limited", "generation_timeout"],
)
async def test_limited_vision_model_still_answers_from_the_transcript(monkeypatch, code):
    calls = []

    async def answer(request, sources, history, context):
        calls.append(request["question"])
        return transcript_answer()

    team = adapters(monkeypatch, error(code, "limited", status=429, retryable=True), answer)
    result = await team._answer_uncached({"question": "บนจอเขียนว่าอะไร"}, [], [], None)

    assert calls == ["บนจอเขียนว่าอะไร"]
    assert result.provider_metadata.fallback_from == "gemini-3.5-flash"
    assert result.coverage.notes[-1].endswith("โควตาวิเคราะห์ภาพและเสียงหมดชั่วคราว")


async def test_limited_transcript_answer_still_reaches_the_callers_local_fallback(monkeypatch):
    async def answer(request, sources, history, context):
        raise error("quota_wait", "every model is limited", status=429, retryable=True)

    team = adapters(monkeypatch, error("quota_wait", "limited", status=429, retryable=True), answer)
    with pytest.raises(Exception) as caught:
        await team._answer_uncached({"question": "บนจอเขียนว่าอะไร"}, [], [], None)

    assert caught.value.code == "quota_wait"


async def test_other_vision_errors_are_not_hidden(monkeypatch):
    async def answer(request, sources, history, context):
        raise AssertionError("transcript answer must not run")

    team = adapters(monkeypatch, error("invalid_model_output", "bad", status=502), answer)
    with pytest.raises(Exception) as caught:
        await team._answer_uncached({"question": "บนจอเขียนว่าอะไร"}, [], [], None)

    assert caught.value.code == "invalid_model_output"
