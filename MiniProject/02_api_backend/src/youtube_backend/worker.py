import asyncio
import logging
import time
from contextlib import suppress

from pydantic import ValidationError

from .errors import AppError, LeaseLost
from .integrations import ExecutionContext
from .schemas import (
    AnswerResult,
    ArtifactResult,
    IndexReceipt,
    ResearchResult,
    Source,
    TranscriptResult,
)
from .validation import validate_result

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, repository, adapters, settings):
        self.repo = repository
        self.adapters = adapters
        self.settings = settings

    async def _heartbeat(self, context):
        while True:
            await asyncio.sleep(self.settings.job_lease_seconds / 3)
            context.check()
            self.repo.heartbeat(context.job_id, context.lease_token)

    async def _process(self, job, context):
        context.check()
        kind, job_id, token = job["kind"], job["job_id"], job["lease_token"]
        if kind == "import":
            self.repo.stage(job_id, token, "fetching_transcript")
            transcript = TranscriptResult.model_validate(
                await self.adapters.ingest(job["video_id"], context)
            )
            context.check()
            source = self.repo.save_transcript(job_id, token, transcript)
            self.repo.stage(job_id, token, "indexing")
            receipt = IndexReceipt.model_validate(
                await self.adapters.index(source, transcript, context)
            )
            if receipt.source != source:
                raise AppError(
                    "adapter_invalid_output", "Index receipt does not match transcript", 502
                )
            count = await self.adapters.inventory([source], context)
            if type(count) is not int or count != receipt.chunk_count:
                raise AppError(
                    "incomplete_index", "Index inventory does not match its receipt", 502
                )
            context.check()
            self.repo.finish(job_id, token, receipt.model_dump())
            return
        if kind == "delete":
            self.repo.stage(job_id, token, "deleting")
            await self.adapters.delete(job["video_id"], job["generation"], context)
            context.check()
            self.repo.finish(job_id, token, {"video_id": job["video_id"], "deleted": True})
            return
        payload = job["payload"]
        sources = [Source.model_validate(s) for s in payload["sources"]]
        request = payload["request"]
        state = "completed"
        if kind == "chat":
            result = AnswerResult.model_validate(
                await self.adapters.answer(request, sources, payload["history"], context)
            )
        elif kind == "analysis":
            result = AnswerResult.model_validate(
                await self.adapters.analyze(request, sources, context)
            )
        elif kind == "artifact":
            result = ArtifactResult.model_validate(
                await self.adapters.artifact(request, sources, context)
            )
            if result.type != request["type"]:
                raise AppError(
                    "adapter_invalid_output", "Artifact type does not match request", 502
                )
            if result.type == "study_plan" and len(result.content.days) != request.get("days", 7):
                raise AppError(
                    "adapter_invalid_output", "Study plan day count does not match request", 502
                )
        elif kind == "research":
            result = ResearchResult.model_validate(
                await self.adapters.research(request, sources, context)
            )
            state = result.state
            for artifact in result.artifacts:
                await validate_result(artifact, sources, self.adapters, context, full_task=True)
            if not result.coverage.complete and state == "completed":
                raise AppError("invalid_coverage", "Incomplete research must be partial", 502)
        else:
            raise AppError("unknown_job_kind", "Unsupported job type", 500)
        result = await validate_result(
            result, sources, self.adapters, context, full_task=kind != "chat"
        )
        self.repo.finish(job_id, token, result.model_dump(mode="json"), state=state)

    async def run_once(self, job_id=None):
        started = time.monotonic()
        job = self.repo.claim(job_id)
        if not job:
            return False
        context = ExecutionContext(
            self.repo, job["job_id"], job["lease_token"], job["deadline_at"], self.settings
        )
        # The request deadline is durable across retries. Chat also observes its HTTP budget.
        remaining = context.remaining_seconds
        if job["kind"] == "chat":
            remaining = min(remaining, self.settings.llm_timeout_seconds)
        process = heartbeat = None
        try:
            async with asyncio.timeout(remaining):
                process = asyncio.create_task(self._process(job, context))
                heartbeat = asyncio.create_task(self._heartbeat(context))
                done, _ = await asyncio.wait(
                    {process, heartbeat}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    await task
        except LeaseLost:
            logger.info("job_lease_lost job_id=%s", job["job_id"])
        except asyncio.CancelledError:
            self._fail_if_owned(
                job, AppError("worker_interrupted", "Worker interrupted", 503, True)
            )
            raise
        except TimeoutError:
            self._fail_if_owned(
                job, AppError("task_timeout", "Task exceeded its deadline", 504, True)
            )
        except ValidationError:
            self._fail_if_owned(
                job, AppError("adapter_invalid_output", "Dependency returned invalid data", 502)
            )
        except AppError as error:
            self._fail_if_owned(job, error)
        except Exception:
            # Deliberately omit exception strings; adapters may embed credentials in them.
            self._fail_if_owned(
                job, AppError("dependency_error", "Dependency failed unexpectedly", 502)
            )
        finally:
            for task in (process, heartbeat):
                if task is not None:
                    task.cancel()
            for task in (process, heartbeat):
                if task is not None:
                    with suppress(asyncio.CancelledError, Exception):
                        await task
        final = self.repo.get_job(job["job_id"])
        logger.info(
            "job_finished job_id=%s request_id=%s kind=%s state=%s stage=%s latency_ms=%.1f",
            job["job_id"],
            job["request_id"],
            job["kind"],
            final["state"],
            final["stage"],
            (time.monotonic() - started) * 1000,
        )
        return True

    def _fail_if_owned(self, job, error):
        with suppress(LeaseLost):
            self.repo.fail(job["job_id"], job["lease_token"], error)

    async def run_forever(self):
        while True:
            if not await self.run_once():
                await asyncio.sleep(self.settings.worker_poll_seconds)
