"""Deterministic, persistent fixtures. No YouTube, Chroma, embeddings or Gemini access."""

import sqlalchemy as sa

from . import database as db
from .errors import AppError
from .schemas import (
    AnswerResult,
    ArtifactResult,
    Citation,
    Coverage,
    Evidence,
    IndexReceipt,
    ProgressEvent,
    ProviderMetadata,
    ResearchResult,
    Segment,
    TranscriptResult,
)


class FixtureAdapters:
    def __init__(self, repository, settings):
        self.repo = repository
        self.settings = settings

    async def ingest(self, video_id, context):
        context.check()
        if video_id == "NoCaption01":
            raise AppError("no_transcript", "Fixture has no accessible captions", 409)
        if video_id == "Unavailable":
            raise AppError("video_unavailable", "Fixture video is unavailable", 404)
        if video_id == "RetryOnce01":
            if self.repo.get_job(context.job_id)["attempt_count"] == 1:
                raise AppError("provider_timeout", "Fixture transient timeout", 504, True)
        return TranscriptResult(
            video_id=video_id,
            title=f"[FIXTURE] RAG lesson {video_id}",
            channel_id="fixture-channel",
            channel_title="[FIXTURE] Learning",
            published_at="2026-01-01",
            language="th",
            source="fixture",
            segments=[
                Segment(
                    segment_id="s1",
                    text="RAG ค้นหลักฐานจากเอกสารก่อนสร้างคำตอบ",
                    start_seconds=0,
                    duration_seconds=12,
                ),
                Segment(
                    segment_id="s2",
                    text="Embeddings แปลงข้อความเป็นเวกเตอร์เพื่อค้นความหมาย",
                    start_seconds=12,
                    duration_seconds=15,
                ),
                Segment(
                    segment_id="s3",
                    text="คำตอบต้องอ้างอิงแหล่งข้อมูลและแจ้งเมื่อหลักฐานไม่พอ",
                    start_seconds=27,
                    duration_seconds=13,
                ),
            ],
        )

    async def index(self, source, transcript, context):
        context.check()
        with self.repo.db.write() as connection:
            self.repo._owned(connection, context.job_id, context.lease_token)
            # This fixture shares the application DB, so fencing and publication are atomic.
            video = (
                connection.execute(
                    sa.select(db.videos).where(db.videos.c.video_id == source.video_id)
                )
                .mappings()
                .one()
            )
            if (
                video["status"] in {"deleting", "deleted"}
                or video["generation"] != source.generation
            ):
                raise AppError("cancelled", "Video is being deleted", 409)
            connection.execute(
                db.fixture_chunks.delete().where(
                    db.fixture_chunks.c.video_id == source.video_id,
                    db.fixture_chunks.c.generation == source.generation,
                )
            )
            for segment in transcript.segments:
                chunk_id = (
                    f"{source.video_id}:g{source.generation}:"
                    f"{source.transcript_version[:12]}:{segment.segment_id}"
                )
                evidence = Evidence(
                    chunk_id=chunk_id,
                    video_id=source.video_id,
                    transcript_version=source.transcript_version,
                    title=transcript.title or f"YouTube {source.video_id}",
                    text=segment.text,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.start_seconds + segment.duration_seconds,
                )
                connection.execute(
                    db.fixture_chunks.insert().values(
                        video_id=source.video_id,
                        generation=source.generation,
                        chunk_id=chunk_id,
                        data=evidence.model_dump(),
                    )
                )
        return IndexReceipt(source=source, chunk_count=len(transcript.segments), complete=True)

    async def delete(self, video_id, generation, context):
        context.check()
        with self.repo.db.write() as connection:
            self.repo._owned(connection, context.job_id, context.lease_token)
            connection.execute(
                db.fixture_chunks.delete().where(
                    db.fixture_chunks.c.video_id == video_id,
                    db.fixture_chunks.c.generation <= generation,
                )
            )

    def _chunks(self, sources):
        results = []
        with self.repo.db.read() as connection:
            for source in sources:
                for data in connection.execute(
                    sa.select(db.fixture_chunks.c.data).where(
                        db.fixture_chunks.c.video_id == source.video_id,
                        db.fixture_chunks.c.generation == source.generation,
                    )
                ).scalars():
                    if data["transcript_version"] == source.transcript_version:
                        results.append(Evidence.model_validate(data))
        return sorted(results, key=lambda e: (e.video_id, e.start_seconds))

    async def inventory(self, sources, context):
        context.check()
        return len(self._chunks(sources))

    async def evidence(self, sources, chunk_ids, context):
        context.check()
        return [c for c in self._chunks(sources) if c.chunk_id in chunk_ids]

    def _metadata(self):
        return ProviderMetadata(
            provider="fixture",
            requested_model=self.settings.llm_model,
            returned_model=None,
            latency_ms=0,
            usage={},
        )

    def _coverage(self, sources):
        count = len(self._chunks(sources))
        return Coverage(
            expected_videos=len(sources),
            processed_videos=len(sources),
            expected_chunks=count,
            processed_chunks=count,
            complete=True,
            notes=["FIXTURE: deterministic data; no model was called"],
        )

    def _citations(self, sources):
        return [
            Citation(
                citation_id=f"c{i}",
                chunk_id=c.chunk_id,
                video_id=c.video_id,
                title=c.title,
                start_seconds=c.start_seconds,
                end_seconds=c.end_seconds,
            )
            for i, c in enumerate(self._chunks(sources), 1)
        ]

    async def answer(self, request, sources, history, context):
        context.check()
        supported = any(
            word in request["question"].lower()
            for word in ("rag", "embedding", "หลักฐาน", "อ้างอิง", "สรุป")
        )
        return AnswerResult(
            status="answered" if supported else "insufficient_evidence",
            answer="[FIXTURE] RAG ค้นหลักฐานก่อนสร้างคำตอบ [c1]"
            if supported
            else "[FIXTURE] ไม่มีหลักฐานสำหรับคำถามนี้",
            citations=self._citations(sources) if supported else [],
            coverage=self._coverage(sources),
            provider_metadata=self._metadata(),
        )

    async def analyze(self, request, sources, context):
        context.check()
        return AnswerResult(
            status="answered",
            answer=f"[FIXTURE] {request['type']}: RAG และการอ้างอิง [c1]",
            citations=self._citations(sources),
            coverage=self._coverage(sources),
            provider_metadata=self._metadata(),
        )

    async def artifact(self, request, sources, context):
        context.check()
        content = {
            "study_plan": {
                "days": [
                    {"day": day, "topic": "[FIXTURE] RAG basics", "citations": ["c1"]}
                    for day in range(1, request.get("days", 7) + 1)
                ]
            },
            "quiz": {
                "questions": [
                    {
                        "question": "[FIXTURE] RAG ค้นอะไรก่อนตอบ?",
                        "answer": "หลักฐาน",
                        "explanation": "ค้นจากเอกสารก่อนสร้างคำตอบ",
                        "citations": ["c1"],
                    }
                ]
            },
            "flashcards": {
                "cards": [
                    {
                        "front": "[FIXTURE] Embeddings",
                        "back": "เวกเตอร์แทนข้อความ",
                        "citations": ["c2"],
                    }
                ]
            },
        }[request["type"]]
        return ArtifactResult(
            type=request["type"],
            content=content,
            citations=self._citations(sources),
            coverage=self._coverage(sources),
            provider_metadata=self._metadata(),
        )

    async def research(self, request, sources, context):
        context.event(
            ProgressEvent(
                step=1,
                tool_name="fixture_read",
                state="completed",
                summary="FIXTURE: read deterministic fixture chunks",
            )
        )
        artifact = await self.artifact(
            dict(type="study_plan", days=request.get("days", 7)), sources, context
        )
        return ResearchResult(
            state="completed",
            content="[FIXTURE] Demonstration only; no autonomous agent ran",
            artifacts=[artifact],
            citations=self._citations(sources),
            coverage=self._coverage(sources),
            provider_metadata=self._metadata(),
        )
