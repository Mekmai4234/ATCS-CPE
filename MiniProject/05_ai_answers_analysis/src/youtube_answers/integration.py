"""05-owned composition of 02/04 boundaries, without changing other modules."""

import time
from collections import OrderedDict

import sqlalchemy as sa
from youtube_backend import database as db
from youtube_backend.schemas import Segment
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import BackendExecution

from .config import AnswerSettings
from .configuration import resolved_service
from .gemini import GeminiModel
from .models import error
from .quota import ExecutionBroker
from .reuse import reuse_configuration
from .service import AnswerService
from .timing import measured_operation, timed_stage


class RagKnowledge:
    def __init__(self, rag):
        self.rag = rag

    async def inventory(self, sources, context):
        return await self.rag.inventory(sources, BackendExecution(context))

    @timed_stage("retrieval")
    async def short_context(self, sources, context):
        return await self.rag.short_context(sources, BackendExecution(context))

    @timed_stage("retrieval")
    async def search(self, query, sources, context, **kwargs):
        return await self.rag.search(query, sources, BackendExecution(context), **kwargs)

    @timed_stage("retrieval")
    async def read(self, sources, context, **kwargs):
        return await self.rag.read_video_chunks(sources, BackendExecution(context), **kwargs)

    async def transcript(self, source, context):
        """Read the frozen version under the durable job's existing authorization."""
        context.check()
        context.authorize_sources([source])
        with context.repository.db.read() as connection:
            condition = sa.and_(
                db.segments.c.video_id == source.video_id,
                db.segments.c.version == source.transcript_version,
            )
            count, size = connection.execute(
                sa.select(
                    sa.func.count(),
                    sa.func.sum(sa.func.length(sa.cast(db.segments.c.text, sa.LargeBinary))),
                ).where(condition)
            ).one()
            if count > 100000 or (size or 0) > 1000000:
                raise error("transcript_too_large", "Transcript exceeds the display budget")
            rows = (
                connection.execute(
                    sa.select(db.segments).where(condition).order_by(db.segments.c.position)
                )
                .mappings()
                .all()
            )
        context.check()
        if not rows:
            raise error("transcript_unavailable", "The frozen transcript has no segments")
        return [
            Segment.model_validate({key: row[key] for key in Segment.model_fields}) for row in rows
        ]

    async def evidence(self, sources, ids, context):
        execution = BackendExecution(context)
        # Whole-video analysis can honestly return partial coverage when an index is missing.
        # 04's evidence() requires ALL supplied indexes; limit this lookup to those available.
        page = await self.rag.read_video_chunks(sources, execution, limit=1)
        missing = {s.video_id for s in page.inventory.missing_sources}
        available = [s for s in sources if s.video_id not in missing]
        if not available:
            return []
        return await self.rag.evidence(available, ids, execution)


class AnswerAdapters(RagAdapters):
    def __init__(
        self,
        *,
        settings,
        repository,
        answer_settings=None,
        model=None,
        rag_settings=None,
        embedder=None,
    ):
        config = answer_settings or AnswerSettings()
        gateway = model or GeminiModel(config, broker=ExecutionBroker(repository, config))
        super().__init__(
            settings=settings, repository=repository, rag_settings=rag_settings, embedder=embedder
        )
        self.answers = AnswerService(config, gateway, RagKnowledge(self.rag))
        self.answer_reuse = OrderedDict()

    @measured_operation("chat")
    @timed_stage("total")
    async def answer(self, request, sources, history, context):
        from youtube_backend.repository import digest

        key = None
        broker = getattr(self.answers.model, "broker", None)
        if isinstance(broker, ExecutionBroker) and context.settings.auth_enabled:
            context.check()
            context.authorize_sources(sources)
            with context.repository.db.read() as connection:
                job = context.repository._owned(connection, context.job_id, context.lease_token)
                context.repository._check_sources(
                    connection, [s.model_dump() for s in sources], owner=job["owner_id"]
                )
            with broker.bind(context):
                grant = self.answers.model.grant(self.answers.settings.llm_model, "chat")
            key = digest(
                [
                    reuse_configuration(self.answers.settings, self.rag.settings),
                    job["owner_id"],
                    [s.model_dump() for s in sources],
                    {k: v for k, v in request.items() if k != "conversation_id"},
                    history,
                    grant.returned_models,
                    self.answers.settings.llm_model,
                ]
            )
            cached = self.answer_reuse.get(key)
            if cached and cached[0] > time.monotonic():
                if any(c.kind == "video" for c in cached[1].citations):
                    from youtube_backend.quota import QuotaBroker

                    QuotaBroker(context.repository).access(
                        cached[1].provider_metadata.requested_model, "generateContent", "vision"
                    )
                result = cached[1].model_copy(deep=True)
                result.provider_metadata.provider = "answer-cache"
                result.provider_metadata.usage = {}
                result.provider_metadata.latency_ms = 0
                return result
        result = await self._answer_uncached(request, sources, history, context)
        if (
            key
            and result.status == "answered"
            and not any(c.kind == "video" for c in result.citations)
            and len(result.model_dump_json().encode()) < 100000
        ):
            self.answer_reuse[key] = (time.monotonic() + 300, result.model_copy(deep=True))
            self.answer_reuse.move_to_end(key)
            while len(self.answer_reuse) > 64:
                self.answer_reuse.popitem(last=False)
        return result

    async def _answer_uncached(self, request, sources, history, context):
        from youtube_backend.errors import AppError

        from .video import NativeVideoAnswers, needs_video

        use_video = needs_video(request["question"])
        video_note = None
        native_insufficient = None
        if use_video and isinstance(self.answers.model, GeminiModel):
            try:
                native = await NativeVideoAnswers(self.answers.model, self.answers.settings).answer(
                    request["question"], sources, context, history=history
                )
                if native is not None and native.status == "answered":
                    return native
                native_insufficient = native
                video_note = "ภาพและเสียงยังยืนยันคำตอบไม่ได้ จึงตรวจบทถอดเสียงเพิ่มเติม"
            except AppError as exc:
                if exc.code not in {
                    "free_tier_unverified",
                    "free_model_unverified",
                    "quota_pending",
                }:
                    raise
                video_note = "คลิปนี้ยังตอบจากบทถอดเสียง: สิทธิ์วิเคราะห์ภาพและเสียงยังไม่พร้อม"
        if isinstance(getattr(self.answers.model, "broker", None), ExecutionBroker):
            with self.answers.model.broker.bind(context):
                result = await self.answers.answer(request, sources, history, context)
        else:
            result = await self.answers.answer(request, sources, history, context)
        if (
            result.status == "insufficient_evidence"
            and not use_video
            and isinstance(self.answers.model, GeminiModel)
        ):
            from .transcript import wants_performer_attribution

            if not wants_performer_attribution(request["question"]):
                try:
                    native = await NativeVideoAnswers(
                        self.answers.model, self.answers.settings
                    ).answer(request["question"], sources, context, history=history)
                    if native is not None:
                        return native
                except AppError as exc:
                    if exc.code not in {
                        "free_tier_unverified",
                        "free_model_unverified",
                        "quota_pending",
                    }:
                        raise
        if result.status == "insufficient_evidence" and native_insufficient is not None:
            return native_insufficient
        if video_note:
            result.coverage.notes.append(video_note)
        return result

    @measured_operation("analysis")
    async def analyze(self, request, sources, context):
        if isinstance(getattr(self.answers.model, "broker", None), ExecutionBroker):
            with self.answers.model.broker.bind(context):
                return await self.answers.analyze(request, sources, context)
        return await self.answers.analyze(request, sources, context)

    async def evidence(self, sources, chunk_ids, context):
        return await self.answers.knowledge.evidence(sources, chunk_ids, context)

    async def close(self):
        try:
            await self.answers.model.close()
        finally:
            await super().close()


async def create_adapters(*, settings, repository):
    from youtube_rag.config import RagSettings

    config = resolved_service(settings, AnswerSettings)
    rag_config = resolved_service(settings, RagSettings)
    gateway = GeminiModel(config, broker=ExecutionBroker(repository, config))
    try:
        return AnswerAdapters(
            settings=settings,
            repository=repository,
            answer_settings=config,
            model=gateway,
            rag_settings=rag_config,
        )
    except BaseException:
        await gateway.close()
        raise
