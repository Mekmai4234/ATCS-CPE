"""Test-only real05 fallback; external captions/embeddings/providers are synthetic.

Both API and worker use this factory only with an explicit isolated runner flag.
No provider credential, client or network model is constructed.
"""

import os

from youtube_answers.config import AnswerSettings
from youtube_answers.integration import AnswerAdapters
from youtube_backend.errors import AppError
from youtube_backend.integrations import UnavailableAdapters
from youtube_backend.schemas import Segment, TranscriptResult
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.manifest import initialize


class UnavailableModel:
    async def generate(self, *args, **kwargs):
        raise AppError("quota_wait", "Explicit synthetic provider outage", 429, True)

    async def close(self):
        pass


class AuditAdapters(UnavailableAdapters):
    capabilities = dict.fromkeys(
        ("ingest", "index", "delete", "evidence", "inventory", "answer"), True
    )

    def __init__(self, answers):
        self.answers = answers
        self.provider_operations = {"index": "local", "answer": "local"}

    async def ingest(self, video_id, context):
        context.check()
        return TranscriptResult(
            video_id=video_id,
            language="th",
            source="fixture",
            title="[FIXTURE] RAG lesson",
            segments=[
                Segment(
                    segment_id="rag",
                    text="RAG retrieves evidence before answering.",
                    start_seconds=0,
                    duration_seconds=10,
                ),
                Segment(
                    segment_id="thai",
                    text="คำตอบต้องมีหลักฐานและอ้างอิงวิดีโอต้นทาง",
                    start_seconds=10,
                    duration_seconds=10,
                ),
            ],
        )

    async def index(self, *args):
        return await self.answers.index(*args)

    async def delete(self, *args):
        return await self.answers.delete(*args)

    async def inventory(self, *args):
        return await self.answers.inventory(*args)

    async def evidence(self, *args):
        return await self.answers.evidence(*args)

    async def answer(self, *args):
        return await self.answers.answer(*args)

    async def close(self):
        await self.answers.close()


async def create_adapters(*, settings, repository):
    if (
        settings.app_env != "test"
        or os.environ.get("WEB_LOCAL_EVIDENCE_TEST") != "true"
    ):
        raise RuntimeError(
            "Only the isolated explicit local-evidence fixture runner may use this factory"
        )
    initialize(repository.db)
    rag = RagSettings(
        _env_file=None,
        embedding_provider="fixture",
        embedding_model="fixture-hash-v1",
        embedding_dimensions=64,
        chroma_persist_dir=settings.chroma_persist_dir,
        chunk_target_tokens=96,
        chunk_overlap_tokens=16,
    )
    return AuditAdapters(
        AnswerAdapters(
            settings=settings,
            repository=repository,
            answer_settings=AnswerSettings(_env_file=None),
            model=UnavailableModel(),
            rag_settings=rag,
            embedder=FixtureEmbedder(rag),
        )
    )
