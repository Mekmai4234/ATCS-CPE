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
from .question_scope import (
    lexical_query,
    overlaps,
    relevant,
    requires_visual,
    retrieval_query,
    time_window,
)
from .quota import ExecutionBroker
from .reuse import reuse_configuration
from .service import AnswerService
from .timing import measured_operation, timed_stage
from .trusted_local import TrustedLocalModel


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
        if isinstance(gateway, TrustedLocalModel):
            self.provider_operations.update(answer="local", analyze="local")
        self.answer_reuse = OrderedDict()

    @measured_operation("chat")
    @timed_stage("total")
    async def answer(self, request, sources, history, context):
        from youtube_backend.errors import AppError

        window = time_window(request["question"], sources[0]) if sources else None
        try:
            result = await self._answer_provider(request, sources, history, context)
        except AppError as exc:
            if (
                exc.code
                not in {
                    "quota_wait",
                    "quota_pending",
                    "free_tier_unverified",
                    "free_model_unverified",
                    "provider_unavailable",
                    "provider_rate_limited",
                    "provider_timeout",
                    "generation_provider_busy",
                    "generation_rate_limited",
                    "generation_unavailable",
                    "generation_timeout",
                }
                or not sources
            ):
                raise
            result = await self._local_answer(request, sources, history, context)
        if any(not overlaps(citation, window) for citation in result.citations):
            raise error(
                "invalid_citation", "Answer evidence is outside the requested time interval"
            )
        return result

    async def _local_answer(self, request, sources, history, context):
        from youtube_backend.schemas import AnswerResult, Citation, Coverage, ProviderMetadata
        from youtube_rag.manifest import BackendExecution

        context.check()
        context.authorize_sources(sources)

        from .authorization import MemberContext, guard_context

        context = guard_context(context, sources, {"chat"})
        if isinstance(context, MemberContext):
            context.conversation(request.get("conversation_id"))
            history = context.history(history)
        started = time.perf_counter()
        window = time_window(request["question"], sources[0])
        query = lexical_query(retrieval_query(request["question"], history))
        # A generic follow-up without an authorized topic cannot be a positive match.
        result = await self.rag.evidence_library().search(
            query or request["question"],
            sources,
            context,
            kinds=["transcript"],
            limit=6,
            neighbors=1,
            start_seconds=window[0] if window else None,
            end_seconds=window[1] if window else None,
        )
        # Re-read each exported reference under this exact execution before publishing.
        records = (
            await self.rag.evidence(
                sources, [item.evidence_id for item in result.items], BackendExecution(context)
            )
            if result.items
            else []
        )
        by_id = {record.chunk_id: record for record in records}
        selected = [
            by_id[item.evidence_id]
            for item in result.items
            if item.evidence_id in by_id
            and query
            and not requires_visual(request["question"])
            and overlaps(by_id[item.evidence_id], window)
            and relevant(query, by_id[item.evidence_id].text)
        ]
        citations = [
            Citation(
                citation_id=str(i + 1),
                chunk_id=record.chunk_id,
                video_id=record.video_id,
                title=record.title,
                start_seconds=record.start_seconds,
                end_seconds=record.end_seconds,
            )
            for i, record in enumerate(selected)
        ]
        notice = (
            "ขณะนี้ AI สร้างคำอธิบายใหม่ไม่ได้ จึงค้นข้อความจากบทถอดเสียงที่บันทึกไว้ให้โดยอัตโนมัติ "
            "ข้อความต่อไปนี้เป็นคำพูดจากคลิป ไม่ใช่ตัวอย่างหรือคำสรุปที่ AI สร้างใหม่"
        )
        text = (
            notice
            + "\n\n"
            + "\n\n".join(record.text + f" [{i + 1}]" for i, record in enumerate(selected))
            if selected
            else (
                "ขณะนี้ AI สร้างคำตอบใหม่ไม่ได้ และยังไม่พบข้อความที่ตรงคำค้นในขอบเขตที่ตรวจ "
                "ลองระบุหัวข้อหรือช่วงเวลาให้ชัดขึ้น การค้นไม่พบไม่ยืนยันว่าไม่มีข้อมูลทั้งคลิป"
            )
        )
        context.check()
        notes = ["ค้นข้อความในเครื่องเท่านั้น ไม่ได้ส่งหลักฐานให้โมเดลสังเคราะห์", *result.notes]
        if requires_visual(request["question"]):
            notes.append("คำถามต้องตรวจภาพซึ่งข้อความบทถอดเสียงยังยืนยันไม่ได้")
        if window:
            notes.append(f"ค้นเฉพาะช่วง {window[0]:g}–{window[1]:g} วินาที; ไม่ยืนยันข้อมูลนอกช่วงนี้")
            if any(r.start_seconds < window[0] or r.end_seconds > window[1] for r in selected):
                notes.append("ข้อความอ้างอิงบางส่วนคร่อมขอบช่วงที่ขอ แสดงเวลาเดิม ไม่ยืนยันว่าทุกคำอยู่ในช่วงนั้น")
        elapsed = (time.perf_counter() - started) * 1000
        return AnswerResult(
            status="answered" if selected else "insufficient_evidence",
            answer=text,
            citations=citations,
            coverage=Coverage(
                expected_videos=len(sources),
                processed_videos=0,
                expected_chunks=None,
                processed_chunks=None,
                complete=False,
                notes=notes,
            ),
            provider_metadata=ProviderMetadata(
                provider="local-evidence",
                requested_model="none",
                latency_ms=elapsed,
                usage={"generate_requests": 0, "local_retrieval_validation_ms": round(elapsed)},
            ),
        )

    async def _answer_provider(self, request, sources, history, context):
        from youtube_backend.repository import digest
        from youtube_backend.schemas import AnswerResult

        durable = getattr(context, "saved_answer", None)
        if callable(durable) and context.settings.auth_enabled and sources:
            signature = digest(
                [
                    "durable-answer-v1",
                    reuse_configuration(self.answers.settings, self.rag.settings),
                    [s.model_dump() for s in sources],
                    {k: v for k, v in request.items() if k != "conversation_id"},
                    history,
                ]
            )
            saved = durable(signature)
            if saved:
                from youtube_backend.validation import validate_result

                result = AnswerResult.model_validate(
                    {name: saved[name] for name in AnswerResult.model_fields if name in saved}
                )
                await validate_result(result, sources, self, context)
                metadata = result.provider_metadata
                metadata.provider = {
                    "gemini": "gemini-cache",
                    "gemini-cache": "gemini-cache",
                    "ollama": "ollama-cache",
                    "ollama-cache": "ollama-cache",
                }.get(metadata.provider, "answer-cache")
                metadata.usage = {}
                metadata.latency_ms = 0
                return result

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
                from youtube_backend.validation import validate_result

                await validate_result(cached[1], sources, self, context)
                if any(c.kind == "video" for c in cached[1].citations):
                    from youtube_backend.quota import QuotaBroker

                    QuotaBroker(context.repository).access(
                        cached[1].provider_metadata.requested_model, "generateContent", "vision"
                    )
                result = cached[1].model_copy(deep=True)
                result.provider_metadata.provider = {
                    "gemini": "gemini-cache",
                    "ollama": "ollama-cache",
                }.get(result.provider_metadata.provider, "answer-cache")
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
        if use_video and isinstance(self.answers.model, TrustedLocalModel):
            raise error(
                "local_unsupported",
                "Text-only local cannot inspect video; ask about the available transcript",
                status=409,
            )
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
    gateway = (
        TrustedLocalModel(config)
        if config.generation_provider == "ollama"
        else GeminiModel(config, broker=ExecutionBroker(repository, config))
    )
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
