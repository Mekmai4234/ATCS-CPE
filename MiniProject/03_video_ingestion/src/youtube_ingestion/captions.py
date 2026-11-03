import asyncio
import json
import os
import subprocess
import sys

from .errors import failure

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
CLEANUP_TIMEOUT_SECONDS = 2.0
REAP_TIMEOUT_SECONDS = 0.5
ERRORS = {
    "no_transcript": ("No usable captions in the requested languages", 409, False),
    "invalid_video_id": ("Provide a valid YouTube video ID", 422, False),
    "video_restricted": ("Captions require unsupported access", 403, False),
    "video_unavailable": ("Video is unavailable or unplayable", 404, False),
    "youtube_access_blocked": ("YouTube blocked access from this environment", 503, False),
    "youtube_rate_limited": ("YouTube temporarily rate limited captions", 503, True),
    "ingest_timeout": ("Caption request exceeded its deadline", 504, True),
    "ingest_unavailable": ("Caption transport is unavailable", 503, True),
    "caption_provider_error": ("YouTube rejected the caption request", 502, False),
    "caption_provider_transient": ("YouTube caption provider is unavailable", 503, True),
}


def remote_error(code):
    code = code if code in ERRORS else "caption_provider_error"
    message, status, retryable = ERRORS[code]
    return failure(code, message, status, retryable)


class SubprocessCaptions:
    """One killable process per fetch; no thread can outlive a cancelled job."""

    def __init__(self):
        self.processes = set()
        self.fetches = set()
        self.stopping = {}
        self.closed = False

    async def _cleanup(self, process):
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
                # wait() alone can deadlock on a paused stdout reader, even after kill().
                # Kill first so communicate() drains only buffered/in-flight pipe data,
                # not an unbounded producer. It also closes the stdout transport.
                await process.communicate()
                if process.stdin is not None:
                    await process.stdin.wait_closed()
        except (TimeoutError, OSError, RuntimeError):
            # asyncio.Process has no public close() API. On failed/stalled drainage,
            # close its transport to release pipe waiters, then bound the final reap.
            process._transport.close()
            try:
                async with asyncio.timeout(REAP_TIMEOUT_SECONDS):
                    await process.wait()
            except TimeoutError:
                self.closed = True
                raise failure(
                    "ingest_cleanup_timeout", "Caption subprocess could not be reaped in time", 503
                ) from None

    async def _stop(self, process):
        task = self.stopping.get(process)
        if task is None:
            task = asyncio.create_task(self._cleanup(process))
            self.stopping[process] = task
        interrupted = False
        try:
            # A second cancellation (for example worker stop during job cancellation)
            # must not abandon pipe cleanup. The cleanup task has its own hard budget.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    if task.cancelled():
                        raise
                    interrupted = True
            task.result()
        finally:
            if task.done():
                self.stopping.pop(process, None)
            if process.returncode is not None:
                self.processes.discard(process)
        if interrupted:
            raise asyncio.CancelledError

    async def fetch(self, video_id, languages, timeout):
        if self.closed:
            raise failure("ingest_unavailable", "Caption adapter is closed", 503)
        process = None
        owner = asyncio.current_task()
        self.fetches.add(owner)
        try:
            async with asyncio.timeout(timeout):
                env = {
                    name: value
                    for name, value in os.environ.items()
                    if not name.upper().endswith(("KEY", "TOKEN", "SECRET", "PASSWORD"))
                }
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "youtube_ingestion.fetch_worker",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                    **(
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if sys.platform == "win32"
                        else {}
                    ),
                )
                self.processes.add(process)
                if self.closed:
                    raise remote_error("ingest_unavailable")
                request = dict(video_id=video_id, languages=languages, timeout=timeout)
                process.stdin.write(json.dumps(request).encode() + b"\n")
                await process.stdin.drain()
                process.stdin.close()
                # Read incrementally: read(n) can return less than n before EOF.
                chunks, count = [], 0
                while chunk := await process.stdout.read(65536):
                    count += len(chunk)
                    if count > MAX_RESPONSE_BYTES:
                        raise failure("invalid_transcript", "Caption response exceeds size limit")
                    chunks.append(chunk)
                await process.wait()
                if process.returncode != 0:
                    raise remote_error("ingest_unavailable")
                response = json.loads(b"".join(chunks))
                if response.get("ok") is not True:
                    raise remote_error(response.get("code"))
                return response["track"]
        except TimeoutError:
            raise remote_error("ingest_timeout") from None
        except (OSError, ConnectionError):
            raise remote_error("ingest_unavailable") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise remote_error("caption_provider_error") from None
        finally:
            try:
                if process is not None:
                    await self._stop(process)
            finally:
                self.fetches.discard(owner)

    async def close(self):
        self.closed = True
        # The fetch coroutine owns stdout. Cancel and join it before another coroutine
        # drains the same StreamReader; concurrent read() calls are not supported.
        active = [task for task in self.fetches if task is not asyncio.current_task()]
        for task in active:
            task.cancel()
        if active:
            results = await asyncio.gather(*active, return_exceptions=True)
            for result in results:
                if getattr(result, "code", None) == "ingest_cleanup_timeout":
                    raise result
        for process in list(self.processes):
            await self._stop(process)
