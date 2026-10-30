import json
from types import SimpleNamespace

import httpx
import pytest
from google import genai
from google.genai import types
from youtube_backend.schemas import Source

from youtube_answers.config import AnswerSettings
from youtube_answers.video import NativeVideoAnswers


@pytest.mark.parametrize("history", [[], [{"role": "user", "content": "ดู 01:20 คนนี้ใคร"}]])
@pytest.mark.parametrize(
    "question,invalid_window", [("บนจอเขียนว่าอะไร", False), ("ในภาพช่วง00:10เห็นอะไร", True)]
)
async def test_native_video_has_scoped_input_timestamps_and_reuses_private_cache(
    monkeypatch, question, invalid_window, history
):
    import youtube_answers.video as module

    sent = []
    output = dict(
        status="answered",
        observations=[dict(id="o1", kind="on_screen", text="RAG", start_seconds=1, end_seconds=2)],
        statements=[dict(text="บนจอเขียนว่า RAG", citation_ids=["o1"])],
    )

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 100})
        return httpx.Response(
            200,
            json=dict(
                candidates=[
                    dict(content=dict(parts=[dict(text=json.dumps(output))]), finishReason="STOP")
                ],
                modelVersion="gemini-3.5-flash",
            ),
        )

    class Store:
        data = None

        def __init__(self, context):
            pass

        def load(self, *args):
            return "a" * 64, self.data

        def publish(self, source, model, question, data, reservation, input_hash):
            assert reservation == "reconciled-proof"
            Store.data = data
            return "a" * 64

    monkeypatch.setattr(module, "VideoEvidenceStore", Store)
    monkeypatch.setattr(
        module,
        "QuotaBroker",
        lambda repo: SimpleNamespace(
            access=lambda *args: (
                None,
                SimpleNamespace(image_capable=True, returned_models=["gemini-3.5-flash"]),
            )
        ),
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = genai.Client(
        api_key="test-only", vertexai=False, http_options=types.HttpOptions(httpx_async_client=http)
    )

    async def call(callback, **request):
        assert request["role"] == "vision"
        result = await callback()
        result.reservation_id = "reconciled-proof"
        return result

    context = SimpleNamespace(repository=object(), remaining_seconds=60, gemini_call=call)
    service = NativeVideoAnswers(SimpleNamespace(client=client), AnswerSettings(_env_file=None))
    source = Source(video_id="dQw4w9WgXcQ", generation=1, transcript_version="v1")
    try:
        if invalid_window:
            from youtube_backend.errors import AppError

            with pytest.raises(AppError, match="inspected time window"):
                await service.answer(question, [source], context, history=history)
            assert Store.data is None
            return
        first = await service.answer(question, [source], context, history=history)
        second = await service.answer(question, [source], context, history=history)
        assert first.citations[0].kind == "video"
        assert first.citations[0].start_seconds == 1
        assert not first.coverage.complete
        assert second.provider_metadata.provider == "video-cache"
        assert len(sent) == 2
        payload = json.loads(sent[0]["contents"][0]["parts"][0]["text"])
        assert payload["window_seconds"] == [0, None]
        assert payload["question"] == question
        assert payload["untrusted_history_references"] == history
        part = sent[0]["contents"][0]["parts"][1]
        assert (
            part["fileData"].get("fileUri", part["fileData"].get("file_uri"))
            == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
    finally:
        await client.aio.aclose()
        client.close()
        await http.aclose()


def test_video_abstention_discards_populated_claims_and_punctuation_only_message():
    from youtube_answers.video import parse_video_output

    value = parse_video_output(
        json.dumps(
            {
                "status": "insufficient_evidence",
                "message": "!!!!!",
                "statements": [{"text": "!!!!!", "citation_ids": ["obs_0"]}],
                "observations": [],
            }
        )
    )
    assert value.status == "insufficient_evidence"
    assert not value.statements and not value.observations
    assert "ยืนยัน" in value.message


@pytest.mark.parametrize(
    "text",
    [
        "not-json",
        '{"status":"answered","observations":[],"statements":[{"text":"invented","citation_ids":["unknown"]}]}',
    ],
)
def test_invalid_native_evidence_is_rejected_without_publishing_claims(text):
    from youtube_backend.errors import AppError

    from youtube_answers.video import parse_video_output

    with pytest.raises(AppError) as caught:
        parse_video_output(text)
    assert caught.value.code == "invalid_model_output"
    assert "invented" not in str(caught.value)
