import asyncio
import json
import os
import subprocess
import sys

from .errors import error


class ChromaStore:
    """Async facade over a killable, persistent local Chroma worker process.

    Cancelling/time-limiting an operation kills and reaps the process. It cannot leave an
    uncancellable thread mutating vectors after its execution lease is lost.
    """

    def __init__(self, path, collection):
        self.path = str(path)
        self.collection = collection
        self.process = None
        self.lock = asyncio.Lock()

    async def _stop(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def call(self, operation, timeout, **args):
        try:
            async with asyncio.timeout(timeout):
                async with self.lock:
                    return await self._communicate(operation, args)
        except TimeoutError:
            raise error(
                "vector_store_timeout", "Chroma operation timed out", status=503, retryable=True
            ) from None

    async def _communicate(self, operation, args):
        try:
            if self.process is None or self.process.returncode is not None:
                env = dict(os.environ)
                # The vector subprocess needs no provider credentials.
                for key in list(env):
                    if key.upper().endswith(("API_KEY", "TOKEN", "SECRET")):
                        env.pop(key)
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "youtube_rag.chroma_worker",
                    self.path,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                    limit=32 * 1024 * 1024,
                    **(
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if sys.platform == "win32"
                        else {}
                    ),
                )
            request = dict(operation=operation, collection=self.collection, args=args)
            self.process.stdin.write((json.dumps(request) + "\n").encode())
            await self.process.stdin.drain()
            line = await self.process.stdout.readline()
            response = json.loads(line)
            if not response.get("ok"):
                raise error(
                    "vector_store_error", "Chroma operation failed", status=503, retryable=True
                )
            return response["result"]
        except BaseException as exc:
            await self._stop()
            if isinstance(exc, (BrokenPipeError, ConnectionError, ValueError)):
                raise error(
                    "vector_store_error", "Chroma process failed", status=503, retryable=True
                ) from None
            raise

    async def close(self):
        async with self.lock:
            await self._stop()
