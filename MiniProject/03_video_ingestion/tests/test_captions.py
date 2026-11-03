import asyncio
import json
import sys
import time

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


async def guarded_result(task, processes, seconds=4):
    """A regression must fail without hanging pytest itself on the original bug."""
    done, _ = await asyncio.wait({task}, timeout=seconds)
    if not done:
        for process in processes:
            process._transport.close()
        await asyncio.wait({task}, timeout=1)
        if not task.done():
            task.cancel()
        pytest.fail("Caption fetch/cleanup exceeded its watchdog budget")
    return await task


async def wait_for_full_pipe(processes, count=1):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if len(processes) == count and all(p.stdout._paused for p in processes):
            return
        await asyncio.sleep(0.01)
    pytest.fail("Child did not fill the actual asyncio stdout pipe")


async def buffered_writer(monkeypatch):
    """Leave the parent reader paused while a real 20 MiB child fills the pipe."""
    original = asyncio.create_subprocess_exec
    processes = []

    async def create(*args, **kwargs):
        process = await original(
            sys.executable,
            "-c",
            "import sys,time; sys.stdout.buffer.write(b'x'*(20*1024*1024)); "
            "sys.stdout.flush(); time.sleep(30)",
            **kwargs,
        )
        read = process.stdout.read

        async def pause_fetch_read(n=-1):
            if n == 65536:
                await asyncio.sleep(30)
            return await read(n)

        monkeypatch.setattr(process.stdout, "read", pause_fetch_read)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    return processes


async def test_real_20_mib_output_exceeds_production_limit_without_cleanup_deadlock(monkeypatch):
    import youtube_ingestion.captions as module

    assert module.MAX_RESPONSE_BYTES == 8 * 1024 * 1024
    processes, _ = await spawn_double(
        monkeypatch,
        "import sys; sys.stdout.buffer.write(b'x'*(20*1024*1024)); sys.stdout.flush()",
    )
    captions = SubprocessCaptions()
    started = time.monotonic()
    task = asyncio.create_task(captions.fetch(VIDEO_A, ["en"], 0.5))
    try:
        with pytest.raises(AppError) as error:
            await guarded_result(task, processes)
        assert error.value.code == "invalid_transcript"
        assert time.monotonic() - started < 3
        assert processes[0].returncode is not None
        assert not captions.processes and not captions.fetches and not captions.stopping
    finally:
        await captions.close()


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancel_with_actual_full_stdout_pipe(monkeypatch, cancel):
    processes = await buffered_writer(monkeypatch)
    captions = SubprocessCaptions()
    task = asyncio.create_task(captions.fetch(VIDEO_A, ["en"], 10 if cancel else 0.5))
    try:
        await wait_for_full_pipe(processes)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else AppError) as error:
            await guarded_result(task, processes)
        if not cancel:
            assert error.value.code == "ingest_timeout"
        assert processes[0].returncode is not None
        assert not captions.processes and not captions.fetches and not captions.stopping
    finally:
        await captions.close()


async def test_repeated_cancellation_still_joins_pipe_cleanup(monkeypatch):
    processes = await buffered_writer(monkeypatch)
    captions = SubprocessCaptions()
    original = captions._cleanup
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(process):
        entered.set()
        await release.wait()
        await original(process)

    monkeypatch.setattr(captions, "_cleanup", delayed)
    task = asyncio.create_task(captions.fetch(VIDEO_A, ["en"], 10))
    try:
        await wait_for_full_pipe(processes)
        task.cancel()
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await guarded_result(task, processes)
        assert processes[0].returncode is not None
        assert not captions.processes and not captions.fetches and not captions.stopping
    finally:
        release.set()
        await captions.close()


async def test_cleanup_timeout_closes_pipe_transport_and_reaps(monkeypatch):
    import youtube_ingestion.captions as module

    processes = await buffered_writer(monkeypatch)
    captions = SubprocessCaptions()
    task = asyncio.create_task(captions.fetch(VIDEO_A, ["en"], 10))
    try:
        await wait_for_full_pipe(processes)

        async def stalled_communicate(*args):
            await asyncio.sleep(30)

        monkeypatch.setattr(processes[0], "communicate", stalled_communicate)
        monkeypatch.setattr(module, "CLEANUP_TIMEOUT_SECONDS", 0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await guarded_result(task, processes)
        assert processes[0].returncode is not None
        assert processes[0]._transport.is_closing()
        assert not captions.processes
    finally:
        await captions.close()


async def test_service_close_joins_all_full_pipe_fetches(monkeypatch, config):
    from conftest import Context

    from youtube_ingestion.service import IngestionService

    processes = await buffered_writer(monkeypatch)
    service = IngestionService(config)
    tasks = [asyncio.create_task(service.ingest(VIDEO_A, Context())) for _ in range(2)]
    try:
        await wait_for_full_pipe(processes, count=2)
        closing = asyncio.create_task(service.close())
        await guarded_result(closing, processes)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert all(process.returncode is not None for process in processes)
        assert not service.captions.processes and not service.captions.fetches
        assert service.metadata.client.is_closed
        await service.close()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()


async def test_final_reap_has_a_hard_budget(monkeypatch):
    import youtube_ingestion.captions as module

    processes = await buffered_writer(monkeypatch)
    captions = SubprocessCaptions()
    task = asyncio.create_task(captions.fetch(VIDEO_A, ["en"], 10))
    try:
        await wait_for_full_pipe(processes)

        async def stalled(*args):
            await asyncio.sleep(30)

        monkeypatch.setattr(processes[0], "communicate", stalled)
        monkeypatch.setattr(processes[0], "wait", stalled)
        monkeypatch.setattr(module, "CLEANUP_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(module, "REAP_TIMEOUT_SECONDS", 0.05)
        task.cancel()
        with pytest.raises(AppError) as error:
            await guarded_result(task, processes, seconds=1)
        assert error.value.code == "ingest_cleanup_timeout"
        assert captions.closed and processes[0].returncode is not None
        assert processes[0]._transport.is_closing()
    finally:
        await captions.close()
