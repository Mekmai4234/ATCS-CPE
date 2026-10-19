"""06-owned composition: reuse 04, implement research/artifact, leave 03/05 explicit."""

from youtube_rag.config import RagSettings
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import BackendExecution

from .config import AgentSettings
from .gemini import GeminiModel
from .service import AgentService


class RagKnowledge:
    def __init__(self, rag):
        self.rag = rag

    async def inventory(self, sources, context):
        return await self.rag.inventory(sources, BackendExecution(context))

    async def search(self, query, sources, context, **kwargs):
        return await self.rag.search(query, sources, BackendExecution(context), **kwargs)

    async def read(self, sources, context, **kwargs):
        return await self.rag.read_video_chunks(sources, BackendExecution(context), **kwargs)

    async def evidence(self, sources, ids, context):
        return await self.rag.evidence(sources, ids, BackendExecution(context))


class AgentAdapters(RagAdapters):
    def __init__(
        self,
        *,
        settings,
        repository,
        agent_settings=None,
        model=None,
        rag_settings=None,
        embedder=None,
        analyzer=None,
    ):
        # Construct the model first so missing generation configuration cannot leak RAG resources.
        config = agent_settings or AgentSettings.from_backend(settings)
        gateway = model or GeminiModel(config)
        rag_settings = rag_settings or RagSettings(
            _env_file=None,
            **{name: getattr(settings, name) for name in RagSettings.model_fields},
        )
        super().__init__(
            settings=settings, repository=repository, rag_settings=rag_settings, embedder=embedder
        )
        self.agent = AgentService(config, gateway, RagKnowledge(self.rag), analyzer=analyzer)

    async def research(self, request, sources, context):
        return await self.agent.research(request, sources, context)

    async def artifact(self, request, sources, context):
        return await self.agent.artifact(request, sources, context)

    async def close(self):
        try:
            await self.agent.model.close()
        finally:
            await super().close()


async def create_adapters(*, settings, repository):
    """Trusted ADAPTER_FACTORY entrypoint. Live ingestion and module 05 are not supplied."""
    config = AgentSettings.from_backend(settings)
    gateway = GeminiModel(config)
    try:
        return AgentAdapters(
            settings=settings, repository=repository, agent_settings=config, model=gateway
        )
    except BaseException:
        await gateway.close()
        raise
