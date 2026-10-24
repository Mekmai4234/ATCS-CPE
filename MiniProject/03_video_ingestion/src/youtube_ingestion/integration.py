"""03-owned composition: live ingestion plus 04. Leaves existing 02/06 factories unchanged."""

from youtube_backend.config import PROJECT_ROOT
from youtube_backend.integrations import UnavailableAdapters
from youtube_rag.config import RagSettings
from youtube_rag.integration import RagAdapters

from .config import IngestionSettings
from .errors import failure
from .service import IngestionService


class IngestionAdapters(UnavailableAdapters):
    capabilities = dict.fromkeys(("ingest", "index", "delete", "evidence", "inventory"), True)

    def __init__(self, ingestion, knowledge):
        self.ingestion, self.knowledge = ingestion, knowledge
        self.closed = False

    async def ingest(self, video_id, context):
        return await self.ingestion.ingest(video_id, context)

    async def prepare_media(self, path, context):
        # Internal opt-in handoff only; 02's current transcript worker does not call it.
        return await self.ingestion.prepare_media(path, context)

    async def index(self, *args):
        return await self.knowledge.index(*args)

    async def delete(self, *args):
        return await self.knowledge.delete(*args)

    async def evidence(self, *args):
        return await self.knowledge.evidence(*args)

    async def inventory(self, *args):
        return await self.knowledge.inventory(*args)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self.ingestion.close()
        finally:
            await self.knowledge.close()


async def create_adapters(*, settings, repository):
    # Live captions must never enter the existing offline demonstration profile.
    if settings.backend_integration_profile != "live":
        raise failure("ingestion_configuration", "Live ingestion requires the live profile", 503)
    config = IngestionSettings()
    rag_config = RagSettings(
        _env_file=(
            PROJECT_ROOT / ".env",
            PROJECT_ROOT / "04_rag_knowledge" / ".env",
            PROJECT_ROOT / "03_video_ingestion" / ".env",
        )
    )
    if rag_config.embedding_provider != "gemini":
        raise failure("ingestion_configuration", "Live ingestion requires Gemini embeddings", 503)
    knowledge = RagAdapters(settings=settings, repository=repository, rag_settings=rag_config)
    # Ingestion owns one metadata client, constructed only after RAG initialized successfully.
    try:
        ingestion = IngestionService(config)
    except BaseException:
        await knowledge.close()
        raise
    return IngestionAdapters(ingestion, knowledge)
