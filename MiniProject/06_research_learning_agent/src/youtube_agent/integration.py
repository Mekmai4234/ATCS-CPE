"""06-owned composition: reuse 04, implement research/artifact, leave 03/05 explicit."""

import hashlib

from youtube_rag.config import RagSettings
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import BackendExecution

from .authorization import MemberAgentService
from .config import AgentSettings
from .local import create_model
from .service import AgentService


class RagKnowledge:
    def __init__(self, rag):
        self.rag = rag

    async def inventory(self, sources, context):
        from youtube_rag.document_knowledge import page

        document = page(context, sources, limit=1)
        if document is not None:
            return document.total
        return await self.rag.inventory(sources, BackendExecution(context))

    async def search(self, query, sources, context, **kwargs):
        from youtube_rag.document_knowledge import search

        document = search(context, sources, query, **kwargs)
        top_k = kwargs.get("top_k", 8)
        if document is not None and len(document) < top_k:
            # Document lookup is exact-phrase only: a paraphrased agent query finds few or
            # no passages, and repeated queries returned the same handful. Top up with
            # passages spread across each transcript (score 0 = not a match), starting
            # at a query-dependent offset so different queries reveal different parts.
            seen = {hit.chunk.chunk_id for hit in document}
            extra = [
                hit
                for hit in self._spread(context, sources, top_k * 2, offset=query)
                if hit.chunk.chunk_id not in seen
            ]
            return document + extra[: top_k - len(document)]
        if document is not None:
            return document
        return await self.rag.search(query, sources, BackendExecution(context), **kwargs)

    def _spread(self, context, sources, top_k, *, offset=""):
        from youtube_rag.document_knowledge import page
        from youtube_rag.models import SearchHit

        from .service import spread_order

        hits = []
        for source in sources:
            chunks, cursor = [], None
            while True:
                current = page(context, [source], limit=200, cursor=cursor)
                if current is None:
                    break
                chunks.extend(current.items)
                cursor = current.next_cursor
                if cursor is None:
                    break
            per_source = max(1, top_k // len(sources))
            shift = int(hashlib.sha256(offset.encode()).hexdigest(), 16) % max(1, len(chunks))
            picked = sorted(
                (i + shift) % len(chunks) for i in spread_order(len(chunks))[:per_source]
            )
            hits.extend(SearchHit(chunk=chunks[i], ranking_score=0) for i in picked)
        return hits

    async def read(self, sources, context, **kwargs):
        from youtube_rag.document_knowledge import page

        document = page(context, sources, **kwargs)
        if document is not None:
            return document
        return await self.rag.read_video_chunks(sources, BackendExecution(context), **kwargs)

    async def evidence(self, sources, ids, context):
        from youtube_rag.document_knowledge import evidence

        document = evidence(context, sources, ids)
        if document is not None:
            return document
        return await self.rag.evidence(sources, ids, BackendExecution(context))


class AgentAdapters(RagAdapters):
    fresh_generation = ("artifact", "research")

    async def inventory(self, sources, context):
        job = context.repository.check_execution(context.job_id, context.lease_token)
        if job["kind"] in {"import", "reindex"}:
            return await super().inventory(sources, context)
        return await RagKnowledge(self.rag).inventory(sources, context)

    async def evidence(self, sources, ids, context):
        return await RagKnowledge(self.rag).evidence(sources, ids, context)

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
        gateway = model or create_model(config)
        rag_settings = rag_settings or RagSettings(
            _env_file=None,
            **{name: getattr(settings, name) for name in RagSettings.model_fields},
        )
        super().__init__(
            settings=settings, repository=repository, rag_settings=rag_settings, embedder=embedder
        )
        self.provider_operations.update(
            {
                name: "local" if config.generation_provider == "ollama" else "gemini-broker-v1"
                for name in ("research", "artifact", "grade_quiz")
            }
        )
        self.agent = AgentService(config, gateway, RagKnowledge(self.rag), analyzer=analyzer)
        if member_authority is not None:
            self.agent = MemberAgentService(self.agent, member_authority)

    async def research(self, request, sources, context):
        return await self.agent.research(request, sources, context)

    async def artifact(self, request, sources, context):
        return await self.agent.artifact(request, sources, context)

    async def grade_quiz(self, request, context):
        job = context.repository.check_execution(context.job_id, context.lease_token)
        if job["kind"] != "quiz_grade":
            from .models import error

            raise error("invalid_operation", "Use a server-owned quiz grading job", status=403)
        agent = self.agent.agent if isinstance(self.agent, MemberAgentService) else self.agent
        result = await agent.model.grade_quiz(
            request,
            min(context.settings.llm_timeout_seconds, context.remaining_seconds),
            context=context,
        )
        context.check()
        return result

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
    gateway = create_model(config)
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
    gateway = create_model(config)
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
