import asyncio
import sys

import pytest
from conftest import Context
from youtube_backend.errors import AppError

from youtube_ingestion.config import MediaSettings
from youtube_ingestion.local_tools import LocalTools


@pytest.fixture
async def tools():
    service = LocalTools(MediaSettings(_env_file=None, tool_timeout_seconds=3))
    yield service
    await service.close()


async def test_actual_tool_resources_and_credentials_are_isolated(tools, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-fixture")
    data = await tools.run(
        [
            sys.executable,
            "-c",
            "import os; print(os.getenv('GEMINI_API_KEY')); print(os.getenv('OMP_THREAD_LIMIT'))",
        ],
        Context(),
    )
    assert data.decode().splitlines() == ["None", "1"]


async def test_output_limit_and_no_raw_error(tools):
    with pytest.raises(AppError) as error:
        await tools.run([sys.executable, "-c", "print('secret'*100000)"], Context(), max_bytes=1024)
    assert error.value.code == "media_tool_output_limit"
    assert "secret" not in error.value.message


async def test_timeout_and_context_revocation_are_bounded(tools):
    tools.settings.tool_timeout_seconds = 0.3
    with pytest.raises(AppError) as error:
        await asyncio.wait_for(
            tools.run([sys.executable, "-c", "import time; time.sleep(20)"], Context()), 4
        )
    assert error.value.code == "media_timeout"
    tools.settings.tool_timeout_seconds = 3
    context = Context()
    task = asyncio.create_task(
        tools.run([sys.executable, "-c", "import time; time.sleep(20)"], context)
    )
    await asyncio.sleep(0.2)
    context.cancelled = True
    with pytest.raises(AppError) as error:
        await asyncio.wait_for(task, 4)
    assert error.value.code == "cancelled"


async def test_cancel_kills_descendant_process(tools, tmp_path):
    marker = tmp_path / "orphan.txt"
    child = (
        "import time; from pathlib import Path; time.sleep(2); "
        f"Path({str(marker)!r}).write_text('orphan')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "print('started',flush=True); time.sleep(20)"
    )
    task = asyncio.create_task(tools.run([sys.executable, "-c", parent], Context()))
    await asyncio.sleep(0.5)
    task.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 4)
    await asyncio.sleep(2)
    assert not marker.exists()


async def test_missing_engine_and_nonzero_exit(tools):
    for command, code in [
        (["03-tool-not-installed"], "media_tool_unavailable"),
        ([sys.executable, "-c", "raise SystemExit(2)"], "media_tool_failed"),
    ]:
        with pytest.raises(AppError) as error:
            await tools.run(command, Context())
        assert error.value.code == code


async def test_capture_stderr_for_pts_without_leaking_it(tools):
    output, diagnostic = await tools.run(
        [sys.executable, "-c", "import sys;print('png');print('pts_time:1.25',file=sys.stderr)"],
        Context(),
        capture_stderr=True,
    )
    assert output.strip() == b"png" and diagnostic.strip() == b"pts_time:1.25"


async def test_shutdown_joins_active_tools(tools):
    task = asyncio.create_task(
        tools.run([sys.executable, "-c", "import time;time.sleep(20)"], Context())
    )
    await asyncio.sleep(0.2)
    await asyncio.wait_for(tools.close(), 4)
    assert task.cancelled() and not tools.tasks


async def test_actual_memory_limit_stops_oversized_child(tools):
    tools.settings.memory_mb = 128
    with pytest.raises(AppError) as error:
        await tools.run(
            [sys.executable, "-c", "a=bytearray(512*1024*1024); print(len(a))"], Context()
        )
    assert error.value.code == "media_tool_failed"


async def test_actual_cpu_limit_stops_busy_child(tools):
    tools.settings.cpu_seconds = 1
    # CPU time differs from wall time; leave room for OS accounting on busy hosts.
    tools.settings.tool_timeout_seconds = 15
    with pytest.raises(AppError) as error:
        await asyncio.wait_for(tools.run([sys.executable, "-c", "while True: pass"], Context()), 18)
    assert error.value.code == "media_tool_failed"
