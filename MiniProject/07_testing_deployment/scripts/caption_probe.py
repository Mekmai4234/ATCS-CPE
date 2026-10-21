"""Bounded regression probe: drain a stuck pipe before reporting a deadline breach."""

import asyncio
import json
import sys
import time

from youtube_backend.errors import AppError
from youtube_ingestion.captions import SubprocessCaptions


async def probe():
    original = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        # Larger than both the real production ceiling (8 MiB) and pipe buffers.
        child = await original(
            sys.executable,
            "-c",
            "import sys; sys.stdin.readline(); sys.stdout.buffer.write(b'x'*(20*1024*1024))",
            **kwargs,
        )
        children.append(child)
        return child

    asyncio.create_subprocess_exec = spawn
    captions = SubprocessCaptions()
    started = time.monotonic()
    task = asyncio.create_task(captions.fetch("dQw4w9WgXcQ", ["en"], 0.5))
    try:
        # asyncio.wait does not cancel the operation: wait_for could hang inside cleanup.
        done, _ = await asyncio.wait({task}, timeout=3)
        within = bool(done)
        if not within:
            for child in children:
                if child.returncode is None:
                    child.kill()
                await asyncio.wait_for(child.stdout.read(), 3)
                await asyncio.wait_for(child.wait(), 3)
            await asyncio.wait({task}, timeout=3)
        code = None
        if task.done():
            try:
                task.result()
            except AppError as exc:
                code = exc.code
        return dict(
            within_deadline=within,
            error_code=code,
            seconds=round(time.monotonic() - started, 3),
            children_reaped=bool(children) and all(c.returncode is not None for c in children),
        )
    finally:
        asyncio.create_subprocess_exec = original
        for child in children:
            if child.returncode is None:
                child.kill()
            await child.communicate()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await captions.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe())))
