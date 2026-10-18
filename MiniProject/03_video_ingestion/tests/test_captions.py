import asyncio
import json
import sys

import pytest
from conftest import VIDEO_A, track
from requests import Response, Session
from youtube_backend.errors import AppError

from youtube_ingestion.captions import SubprocessCaptions
from youtube_ingestion.errors import classify
from youtube_ingestion.fetch_worker import fetch


def test_actual_sdk_http_parsing_without_youtube_network(monkeypatch):
    requests = []

    def send(session, request, **kwargs):
        requests.append(request)
        assert kwargs["timeout"] == 2
        response = Response()
        response.status_code, response.encoding = 200, "utf-8"
        if request.method == "POST":
            assert json.loads(request.body)["videoId"] == VIDEO_A
            data = {
                "playabilityStatus": {"status": "OK"},
                "captions": {
                    "playerCaptionsTracklistRenderer": {
                        "captionTracks": [
                            {
                                "baseUrl": "https://www.youtube.com/api/timedtext?v=" + VIDEO_A,
                                "name": {"runs": [{"text": "Thai"}]},
                                "languageCode": "th",
                            }
                        ]
                    }
                },
            }
            response._content = json.dumps(data).encode()
        elif "/api/timedtext" in request.url:
            response._content = (
                '<transcript><text start="1.25" dur="2.5">ภาษาไทย &amp; RAG</text></transcript>'
            ).encode()
        else:
            response._content = b'<html>"INNERTUBE_API_KEY":"TEST_KEY"</html>'
        return response

    monkeypatch.setattr(Session, "send", send)
    response = fetch(VIDEO_A, ["th", "en"], 2)
    assert response["ok"] and len(requests) == 3
    assert response["track"]["segments"] == [
        {"text": "ภาษาไทย & RAG", "start": 1.25, "duration": 2.5}
    ]


async def spawn_double(monkeypatch, code):
    original = asyncio.create_subprocess_exec
    processes, environments = [], []

    async def create(*args, **kwargs):
        environments.append(kwargs.get("env", {}))
        process = await original(sys.executable, "-c", code, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    return processes, environments


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (429, "youtube_rate_limited", True),
        (503, "caption_provider_transient", True),
        (403, "caption_provider_error", False),
    ],
)
def test_actual_sdk_preserves_http_failure_classification(monkeypatch, status, code, retryable):
    def send(session, request, **kwargs):
        response = Response()
        response.status_code = status
        response._content = b"SECRET upstream message"
        response.request = request
        return response

    monkeypatch.setattr(Session, "send", send)
    with pytest.raises(Exception) as raised:
        fetch(VIDEO_A, ["en"], 2)
    error = classify(raised.value)
    assert error.code == code and error.retryable == retryable
    assert "SECRET" not in error.message


async def test_subprocess_json_unicode_and_secret_environment(monkeypatch):
    response = json.dumps({"ok": True, "track": track()})
    processes, environments = await spawn_double(
        monkeypatch, "import sys; sys.stdin.readline(); print(" + repr(response) + ")"
    )
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET")
    captions = SubprocessCaptions()
    assert (await captions.fetch(VIDEO_A, ["th", "en"], 5))["language"] == "th"
    assert "GEMINI_API_KEY" not in environments[0]
    assert processes[0].returncode == 0 and not captions.processes
    await captions.close()


async def test_timeout_kills_and_reaps_actual_child(monkeypatch):
    processes, _ = await spawn_double(monkeypatch, "import time; time.sleep(30)")
    captions = SubprocessCaptions()
    with pytest.raises(AppError) as error:
        await captions.fetch(VIDEO_A, ["en"], 0.2)
    assert error.value.code == "ingest_timeout" and error.value.retryable
    assert processes and processes[0].returncode is not None and not captions.processes
    await captions.close()


async def test_cancel_kills_and_reaps_actual_child(monkeypatch):
    processes, _ = await spawn_double(monkeypatch, "import time; time.sleep(30)")
    captions = SubprocessCaptions()
    task = asyncio.create_task(captions.fetch(VIDEO_A, ["en"], 10))
    while not processes:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None and not captions.processes
    await captions.close()


@pytest.mark.parametrize(
    "response,code",
    [
        ('{"ok":false,"code":"youtube_rate_limited"}', "youtube_rate_limited"),
        ('{"ok":false,"code":"caption_provider_transient"}', "caption_provider_transient"),
        ('{"ok":false,"code":"SECRET"}', "caption_provider_error"),
        ("invalid JSON SECRET", "caption_provider_error"),
        ('{"ok":true}', "caption_provider_error"),
    ],
)
async def test_subprocess_errors_redacted(monkeypatch, response, code):
    await spawn_double(
        monkeypatch, "import sys; sys.stdin.readline(); print(" + repr(response) + ")"
    )
    captions = SubprocessCaptions()
    with pytest.raises(AppError) as error:
        await captions.fetch(VIDEO_A, ["en"], 5)
    assert error.value.code == code and "SECRET" not in error.value.message
    await captions.close()


async def test_oversized_process_output_is_rejected(monkeypatch):
    import youtube_ingestion.captions as module

    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 100)
    processes, _ = await spawn_double(monkeypatch, "print('x'*100000)")
    captions = SubprocessCaptions()
    with pytest.raises(AppError) as error:
        await captions.fetch(VIDEO_A, ["en"], 5)
    assert error.value.code == "invalid_transcript" and processes[0].returncode is not None
    await captions.close()


async def test_real_worker_invalid_id_never_fetches_network():
    captions = SubprocessCaptions()
    with pytest.raises(AppError):
        await captions.fetch("not-valid", ["en"], 5)
    assert not captions.processes
    await captions.close()
