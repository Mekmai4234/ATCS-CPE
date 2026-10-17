"""02-owned composition of unchanged 04/06 packages. 03/05 remain unavailable."""

from .errors import AppError
from .integrations import UnavailableAdapters


class TeamAdapters(UnavailableAdapters):
    capabilities = dict.fromkeys(
        ("index", "delete", "evidence", "inventory", "research", "artifact"), True
    )

    def __init__(self, knowledge, agent):
        self.knowledge, self.agent = knowledge, agent
        self.closed = False

    async def index(self, *args):
        return await self.knowledge.index(*args)

    async def delete(self, *args):
        return await self.knowledge.delete(*args)

    async def evidence(self, *args):
        return await self.knowledge.evidence(*args)

    async def inventory(self, *args):
        return await self.knowledge.inventory(*args)

    async def research(self, *args):
        return await self.agent.research(*args)

    async def artifact(self, *args):
        return await self.agent.artifact(*args)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self.agent.model.close()
        finally:
            await self.knowledge.close()


async def create_adapters(*, settings, repository):
    try:
        from youtube_agent.config import AgentSettings
        from youtube_agent.gemini import GeminiModel
        from youtube_agent.integration import RagKnowledge
        from youtube_agent.service import AgentService
        from youtube_rag.config import RagSettings
        from youtube_rag.integration import RagAdapters
    except ImportError:
        raise AppError(
            "integration_not_installed",
            "Install the 02 integration environment before starting",
            503,
        ) from None

    from .offline_model import OfflineModel

    # Explicit construction prevents module-local .env files from giving API, worker
    # and agent different budgets or provider identities. User files are never edited.
    agent_config = AgentSettings(
        _env_file=None, **{name: getattr(settings, name) for name in AgentSettings.model_fields}
    )
    offline = settings.backend_integration_profile == "offline"
    if offline and settings.app_env not in {"test", "development"}:
        raise AppError("fixture_forbidden", "Offline integration is for development/test", 503)
    if not offline and not settings.gemini_api_key.get_secret_value():
        raise AppError(
            "generation_unavailable", "GEMINI_API_KEY is required for live integration", 503
        )
    rag_values = {name: getattr(settings, name) for name in RagSettings.model_fields}
    if offline:
        rag_values.update(
            embedding_provider="fixture", embedding_model="fixture-hash-v1", embedding_dimensions=64
        )
    elif settings.embedding_provider != "gemini":
        raise AppError(
            "integration_configuration", "Live integration requires Gemini embeddings", 503
        )
    rag_config = RagSettings(_env_file=None, **rag_values)
    knowledge = RagAdapters(settings=settings, repository=repository, rag_settings=rag_config)
    model = None
    try:
        model = OfflineModel(settings.llm_model) if offline else GeminiModel(agent_config)
        agent = AgentService(agent_config, model, RagKnowledge(knowledge.rag))
        return TeamAdapters(knowledge, agent)
    except BaseException:
        try:
            if model is not None:
                await model.close()
        finally:
            await knowledge.close()
        raise
