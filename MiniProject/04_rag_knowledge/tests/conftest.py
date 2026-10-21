import time
from types import SimpleNamespace

import pytest
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.integrations import ExecutionContext
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.schemas import Segment, Source, TranscriptResult

from youtube_rag.config import RagSettings
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import BackendExecution, initialize

VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "jNQXAC9IVRw"


def transcript(video_id=VIDEO_A, *, text=None):
    return TranscriptResult(
        video_id=video_id,
        title=f"[FIXTURE] {video_id}",
        channel_id="channel-a",
        published_at="2026-01-01",
        language="th",
        source="fixture",
        segments=[
            Segment(
                segment_id="s1",
                text=text or "RAG retrieves evidence before answering questions",
                start_seconds=0,
                duration_seconds=12,
            ),
            Segment(
                segment_id="s2",
                text="Embeddings vectors represent text for semantic retrieval",
                start_seconds=12,
                duration_seconds=15,
            ),
            Segment(
                segment_id="s3",
                text="คำตอบต้องมีหลักฐานและอ้างอิงกลับไปที่คลิปต้นทาง",
                start_seconds=27,
                duration_seconds=13,
            ),
        ],
    )


@pytest.fixture
def config(tmp_path):
    return RagSettings(
        _env_file=None,
        embedding_provider="fixture",
        embedding_model="fixture-hash-v1",
        embedding_dimensions=64,
        chroma_persist_dir=tmp_path / "chroma",
        chunk_target_tokens=96,
        chunk_overlap_tokens=16,
    )


class Environment:
    def context(self, job):
        return ExecutionContext(
            self.repo, job["job_id"], job["lease_token"], job["deadline_at"], self.settings
        )

    def prepare(self, video=VIDEO_A, *, value=None):
        item = self.repo.import_urls([f"https://youtu.be/{video}"])[0]
        job = self.repo.claim(item["job_id"])
        value = value or transcript(video)
        ctx = self.context(job)
        source = self.repo.save_transcript(job["job_id"], job["lease_token"], value)
        self.repo.stage(job["job_id"], job["lease_token"], "indexing")
        return SimpleNamespace(
            source=source, transcript=value, ctx=ctx, execution=BackendExecution(ctx), job=job
        )

    async def ready(self, video=VIDEO_A, *, value=None):
        prepared = self.prepare(video, value=value)
        receipt = await self.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
        self.repo.finish(prepared.job["job_id"], prepared.job["lease_token"], receipt.model_dump())
        return prepared.source

    def query(self, *videos, **filters):
        request = dict(question="RAG evidence", scope=dict(video_ids=list(videos), **filters))
        queued = self.repo.enqueue("chat", request)
        job = self.repo.claim(queued["job_id"])
        return SimpleNamespace(
            job=job,
            sources=[Source.model_validate(s) for s in job["payload"]["sources"]],
            ctx=self.context(job),
            execution=BackendExecution(self.context(job)),
        )


@pytest.fixture
async def env(tmp_path, config):
    result = Environment()
    result.settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=False,
        adapter_mode="custom",
        adapter_factory="youtube_rag.integration:create_adapters",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        job_lease_seconds=120,
        job_retry_base_seconds=0,
        job_timeout_seconds=300,
    )
    result.db = Database(result.settings.database_url)
    upgrade_database(result.db)
    initialize(result.db)
    result.repo = Repository(result.db, result.settings)
    result.config = config
    result.adapters = RagAdapters(
        settings=result.settings,
        repository=result.repo,
        rag_settings=config,
        embedder=FixtureEmbedder(config),
    )
    result.rag = result.adapters.rag
    yield result
    await result.adapters.close()
    result.db.close()


def expire(env, job):
    from youtube_backend import database as db

    with env.db.write() as connection:
        connection.execute(
            db.jobs.update()
            .where(db.jobs.c.job_id == job["job_id"])
            .values(lease_until=time.time() - 1)
        )
