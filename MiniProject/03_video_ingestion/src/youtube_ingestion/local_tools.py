"""Bounded, cancellable local processes with resource limits and tree cleanup."""

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

from .errors import failure


class LocalTools:
    def __init__(self, settings):
        self.settings = settings
        self.tasks = set()
        self.closed = False

    async def run(self, command, context, *, max_bytes=1024 * 1024, capture_stderr=False):
        if self.closed:
            raise failure("media_closed", "Local media adapter is closed", 503)
        context.check()
        task = asyncio.current_task()
        self.tasks.add(task)
        process = reader = errors = None
        # Inherit runtime essentials, never API keys/cookies or provider configuration.
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LD_LIBRARY_PATH"}
        }
        env.update(OMP_THREAD_LIMIT="1", OPENBLAS_NUM_THREADS="1")
        try:
            timeout = min(self.settings.tool_timeout_seconds, context.remaining_seconds)
            async with asyncio.timeout(timeout):
                spawning = asyncio.create_task(
                    asyncio.create_subprocess_exec(
                        sys.executable,
                        "-I",
                        str(Path(__file__).with_name("_local_tool.py")),
                        str(self.settings.memory_mb),
                        str(self.settings.cpu_seconds),
                        *map(str, command),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                        if capture_stderr
                        else asyncio.subprocess.DEVNULL,
                        stdin=asyncio.subprocess.DEVNULL,
                        env=env,
                        **(
                            {"creationflags": subprocess.CREATE_NO_WINDOW}
                            if os.name == "nt"
                            else {"start_new_session": True}
                        ),
                    )
                )
                try:
                    process = await asyncio.shield(spawning)
                except asyncio.CancelledError:
                    while not spawning.done():
                        try:
                            await asyncio.shield(spawning)
                        except asyncio.CancelledError:
                            continue
                    process = spawning.result()
                    raise

                async def read(stream, limit):
                    data = bytearray()
                    while block := await stream.read(65536):
                        data.extend(block)
                        if len(data) > limit:
                            raise failure(
                                "media_tool_output_limit",
                                "Local tool output exceeded its limit",
                                422,
                            )
                    return bytes(data)

                reader = asyncio.create_task(read(process.stdout, max_bytes))
                if capture_stderr:
                    errors = asyncio.create_task(read(process.stderr, 65536))
                waiting = {reader} | ({errors} if errors is not None else set())
                while waiting:
                    done, waiting = await asyncio.wait(waiting, timeout=0.05)
                    context.check()
                    for task_done in done:
                        task_done.result()
                result = await reader
                while process.returncode is None:
                    await asyncio.sleep(0.05)
                    context.check()
                context.check()
                if process.returncode:
                    code = {
                        125: "media_resource_limits_unavailable",
                        127: "media_tool_unavailable",
                    }.get(process.returncode, "media_tool_failed")
                    raise failure(
                        code,
                        "Local media tool could not complete",
                        503 if process.returncode in {125, 127} else 422,
                    )
                return (result, errors.result()) if capture_stderr else result
        except TimeoutError:
            raise failure(
                "media_timeout", "Local media tool exceeded its deadline", 504, True
            ) from None
        finally:
            # Shield one bounded cleanup from repeated cancellation; do not orphan descendants.
            async def cleanup():
                if process is not None:
                    if os.name != "nt":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    elif process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    reading = [t for t in (reader, errors) if t is not None]
                    for reading_task in reading:
                        reading_task.cancel()
                    await asyncio.gather(*reading, return_exceptions=True)
                    try:
                        async with asyncio.timeout(2.5):
                            await process.communicate()
                    except (TimeoutError, OSError, RuntimeError):
                        process._transport.close()
                        raise failure(
                            "media_cleanup_timeout", "Local tool cleanup failed", 503
                        ) from None

            cleaning = asyncio.create_task(cleanup())
            cancelled = False
            while not cleaning.done():
                try:
                    await asyncio.shield(cleaning)
                except asyncio.CancelledError:
                    cancelled = True
                    continue
            self.tasks.discard(task)
            cleaning.result()
            if cancelled:
                raise asyncio.CancelledError

    async def close(self):
        self.closed = True
        tasks = list(self.tasks - {asyncio.current_task()})
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
