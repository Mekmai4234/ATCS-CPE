"""04-only bridge to module 02's async Adapters protocol.

The team composition factory can delegate these four methods and reuse .rag for 05/06.
Ingest/generation methods deliberately retain module 02's dependency_unavailable behavior.
"""

from youtube_backend.integrations import UnavailableAdapters

from .config import RagSettings
from .embeddings import FixtureEmbedder, GeminiEmbedder
from .errors import error
from .manifest import BackendExecution, Manifest
from .service import RagService


class RagAdapters(UnavailableAdapters):
    def __init__(self, *, settings, repository, rag_settings=None, embedder=None):
        config = rag_settings or RagSettings()
        if config.embedding_provider == "fixture" and settings.app_env not in {
            "development",
            "test",
        }:
            raise error(
                "fixture_forbidden", "Fixture embeddings are restricted to development/test"
            )
        self.provider_operations = {
            "index": "local" if config.embedding_provider == "fixture" else "gemini-broker-v1"
        }
        self.rag = RagService(
            config,
            Manifest(repository.db),
            embedder
            or (
                FixtureEmbedder(config)
                if config.embedding_provider == "fixture"
                else GeminiEmbedder(config)
            ),
        )

    async def index(self, source, transcript, context):
        return await self.rag.index(source, transcript, BackendExecution(context))

    async def index_media(self, snapshot, context, *, semantic=True):
        return await self.rag.media.index(snapshot, BackendExecution(context), semantic=semantic)

    async def index_snapshot(self, snapshot, context, *, transcript=None, semantic=True):
        from youtube_backend.evidence_v2 import SourceSnapshotV2

        from .models import transcript_source

        snapshot = SourceSnapshotV2.model_validate(snapshot)
        if snapshot.kind == "transcript":
            if transcript is None:
                raise error("invalid_transcript", "An actual versioned transcript is required")
            return await self.index(transcript_source(snapshot), transcript, context)
        if transcript is not None:
            raise error("invalid_transcript", "Media evidence is not a transcript")
        return await self.index_media(snapshot, context, semantic=semantic)

    async def search_snapshots(self, question, snapshots, context, **options):
        from youtube_backend.evidence_v2 import SourceSnapshotV2

        from .models import transcript_source

        snapshots = [SourceSnapshotV2.model_validate(s) for s in snapshots]
        if snapshots and all(s.kind == "transcript" for s in snapshots):
            return await self.rag.search(
                question,
                [transcript_source(s) for s in snapshots],
                BackendExecution(context),
                **options,
            )
        if any(s.kind == "transcript" for s in snapshots):
            raise error(
                "invalid_scope", "02 has no mixed transcript/media frozen job scope", status=403
            )
        return await self.search_media(question, snapshots, context, **options)

    async def search_media(self, question, snapshots, context, **options):
        return await self.rag.media.search(
            question, snapshots, BackendExecution(context), **options
        )

    async def evidence_media(self, snapshots, evidence_ids, context):
        return await self.rag.media.evidence(snapshots, evidence_ids, BackendExecution(context))

    async def inventory_media(self, snapshots, context):
        return await self.rag.media.inventory(snapshots, BackendExecution(context))

    async def delete(self, video_id, generation, context):
        await self.rag.delete(video_id, generation, BackendExecution(context))

    async def evidence(self, sources, chunk_ids, context):
        return await self.rag.evidence(sources, chunk_ids, BackendExecution(context))

    async def inventory(self, sources, context):
        return await self.rag.inventory(sources, BackendExecution(context))

    async def close(self):
        await self.rag.close()


def create_adapters(*, settings, repository):
    return RagAdapters(settings=settings, repository=repository)
