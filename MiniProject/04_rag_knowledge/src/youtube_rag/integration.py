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
