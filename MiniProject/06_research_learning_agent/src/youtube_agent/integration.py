"""06-owned composition: reuse 04, implement research/artifact, leave 03/05 explicit."""

from youtube_rag.config import RagSettings
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import BackendExecution

from .authorization import MemberAgentService
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
        member_authority=None,
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
        if member_authority is not None:
            self.agent = MemberAgentService(self.agent, member_authority)

    async def research(self, request, sources, context):
        return await self.agent.research(request, sources, context)

    async def artifact(self, request, sources, context):
        return await self.agent.artifact(request, sources, context)

    async def research_media(self, request, snapshots, context, *, planner=None, vision=None):
        """Internal v2 handoff only. 02 does not publish this through v1 research jobs."""
        from .media import MediaAgentService

        tools = RagMediaTools(self.rag)
        agent = self.agent.agent if isinstance(self.agent, MemberAgentService) else self.agent
        return await MediaAgentService(
            agent.settings, tools, planner=planner, vision=vision
        ).research(request, snapshots, context)

    async def close(self):
        try:
            agent = self.agent.agent if isinstance(self.agent, MemberAgentService) else self.agent
            await agent.model.close()
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


async def create_member_adapters(*, settings, repository):
    """Member entrypoint; do not fall back to legacy execution when 02 is unavailable."""
    from .models import error

    authority = getattr(repository, "agent_authority", None)
    if authority is None:
        raise error("member_authority_unavailable", "Backend member authority required", status=503)
    config = AgentSettings.from_backend(settings)
    gateway = GeminiModel(config)
    try:
        return AgentAdapters(
            settings=settings,
            repository=repository,
            agent_settings=config,
            model=gateway,
            member_authority=authority,
        )
    except BaseException:
        await gateway.close()
        raise


class RagMediaTools:
    """Reuse 04's native lexical/enrichment boundary without inventing a research scope."""

    def __init__(self, rag):
        self.media = rag.media

    def authorize(self, sources, context):
        import hashlib

        from .gemini import json_text

        scope = self.media.scope(sources, BackendExecution(context))
        return hashlib.sha256(
            json_text([scope, context.job_id, context.lease_token]).encode()
        ).hexdigest()

    async def inventory(self, sources, context):
        return await self.media.inventory(sources, BackendExecution(context))

    async def search(self, question, sources, context):
        values = await self.media.search(
            question, sources, BackendExecution(context), mode="lexical"
        )
        return [
            {"evidence_id": v["evidence_id"], "citation": v["citation"]} for v in values["hits"]
        ]

    async def evidence(self, sources, ids, context):
        return await self.media.evidence(sources, ids, BackendExecution(context))

    async def frames(self, sources, context):
        self.authorize(sources, context)
        return [
            r["citation"]["frame_id"]
            for s in sources
            for r in self.media.local(s, BackendExecution(context))[0]
        ]
