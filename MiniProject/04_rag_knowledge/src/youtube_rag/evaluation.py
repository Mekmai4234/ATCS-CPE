"""Small reference evaluator; offline hash scores are explicitly not AI quality scores."""

import json
from pathlib import Path

import sqlalchemy as sa
from youtube_backend import database as db
from youtube_backend.config import MODULE_ROOT, Settings
from youtube_backend.database import Database
from youtube_backend.fixture_adapter import FixtureAdapters
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.schemas import Source, TranscriptResult
from youtube_backend.worker import Worker

from .config import RagSettings
from .embeddings import FixtureEmbedder, GeminiEmbedder
from .integration import RagAdapters
from .maintenance import MaintenanceExecution
from .manifest import initialize


class ReferencePipeline(FixtureAdapters):
    """Local reference transcripts + real module 04; no live 03/05/06 behavior."""

    def __init__(self, repository, settings, knowledge, values):
        super().__init__(repository, settings)
        self.knowledge = knowledge
        self.values = {v.video_id: v for v in values}

    async def ingest(self, video_id, context):
        context.check()
        return self.values[video_id]

    async def index(self, *args):
        return await self.knowledge.index(*args)

    async def inventory(self, *args):
        return await self.knowledge.inventory(*args)

    async def evidence(self, *args):
        return await self.knowledge.evidence(*args)

    async def delete(self, *args):
        return await self.knowledge.delete(*args)


async def evaluate(state: Path, *, phase="seed", live=False, dataset=None):
    state = state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    dataset = dataset or MODULE_ROOT.parent / "04_rag_knowledge" / "fixtures" / "evaluation.json"
    reference = json.loads(Path(dataset).read_text(encoding="utf-8"))
    backend = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=False,
        adapter_mode="fixture",
        database_url=f"sqlite:///{(state / 'app.db').as_posix()}",
        job_lease_seconds=30,
        job_timeout_seconds=600,
    )
    database = Database(backend.database_url)
    knowledge = None
    try:
        upgrade_database(database)
        initialize(database)
        repository = Repository(database, backend)
        overrides = (
            {}
            if live
            else dict(
                embedding_provider="fixture",
                embedding_model="fixture-hash-v1",
                embedding_dimensions=128,
            )
        )
        config = RagSettings(
            chroma_persist_dir=state / "chroma",
            chunk_target_tokens=160,
            chunk_overlap_tokens=24,
            **overrides,
        )
        if live and config.embedding_provider != "gemini":
            raise ValueError("Live evaluation requires EMBEDDING_PROVIDER=gemini")
        embedder = GeminiEmbedder(config) if live else FixtureEmbedder(config)
        knowledge = RagAdapters(
            settings=backend, repository=repository, rag_settings=config, embedder=embedder
        )
        values = [TranscriptResult.model_validate(item) for item in reference["videos"]]
        if phase == "seed":
            pipeline = ReferencePipeline(repository, backend, knowledge, values)
            worker = Worker(repository, pipeline, backend)
            for value in values:
                item = repository.import_urls([f"https://youtu.be/{value.video_id}"])[0]
                if item["outcome"] == "accepted":
                    await worker.run_once(item["job_id"])
                if repository.get_job(item["job_id"])["stage"] != "ready":
                    raise RuntimeError("Reference import failed; inspect isolated demo job")
        with database.read() as connection:
            sources = [
                Source(
                    video_id=row["video_id"],
                    generation=row["generation"],
                    transcript_version=row["transcript_version"],
                )
                for row in connection.execute(
                    sa.select(db.videos).where(db.videos.c.status == "ready")
                ).mappings()
            ]
        if len(sources) != len(values):
            raise RuntimeError("Reference database does not contain the expected ready videos")
        execution = MaintenanceExecution(database)
        checks = []
        for item in reference["questions"]:
            scope = [s for s in sources if s.video_id == item["video_id"]]
            hits = await knowledge.rag.search(item["question"], scope, execution, top_k=3)
            rank = next(
                (i for i, hit in enumerate(hits, 1) if item["segment_id"] in hit.chunk.segment_ids),
                None,
            )
            checks.append(
                dict(
                    question=item["question"],
                    expected_segment=item["segment_id"],
                    rank=rank,
                    chunk_ids=[h.chunk.chunk_id for h in hits],
                    scope_ok=all(h.chunk.video_id == item["video_id"] for h in hits),
                )
            )
        count = await knowledge.rag.inventory(sources, execution)
        page = await knowledge.rag.read_video_chunks(sources, execution)
        if len(page.items) != count or not page.inventory.complete:
            raise RuntimeError("Reference coverage check failed")
        result = dict(
            mode="live-gemini" if live else "offline-fixture-hash",
            phase=phase,
            semantic_quality_evaluated=live,
            limitation="Eight synthetic questions are a smoke dataset, not production accuracy.",
            embedding_provider=config.embedding_provider,
            embedding_model=config.embedding_model,
            index_configuration=config.fingerprint,
            videos=len(sources),
            chunks=count,
            questions=len(checks),
            reference_recall_at_3=sum(c["rank"] is not None for c in checks) / len(checks),
            scope_checks_passed=all(c["scope_ok"] for c in checks),
            count_requests=getattr(embedder, "count_requests", 0),
            embedding_requests=getattr(embedder, "embed_requests", 0),
            counted_input_tokens=getattr(embedder, "counted_input_tokens", 0),
            checks=checks,
        )
        marker = state / "seed-result.json"
        if phase == "seed":
            marker.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            seed = json.loads(marker.read_text(encoding="utf-8"))
            if seed["checks"] != result["checks"] or seed["chunks"] != result["chunks"]:
                raise RuntimeError("Persisted results changed after process/container restart")
            result["restart_verified"] = True
        return result
    finally:
        if knowledge is not None:
            await knowledge.close()
        database.close()
