"""Optional 05-owned full team composition; shares one RAG instance for all tools."""

from youtube_backend.integrations import UnavailableAdapters

from .configuration import load_team_configuration
from .gemini import GeminiModel
from .integration import AnswerAdapters, RagKnowledge
from .models import error
from .quota import ExecutionBroker


class TeamAdapters(UnavailableAdapters):
    capabilities = dict.fromkeys(
        (
            "ingest",
            "index",
            "delete",
            "evidence",
            "inventory",
            "answer",
            "analyze",
            "research",
            "artifact",
        ),
        True,
    )

    def __init__(self, answers, ingestion, agent):
        self.answers, self.ingestion, self.agent = answers, ingestion, agent
        self.provider_operations = dict(answers.provider_operations)
        answer_mode = (
            "gemini-broker-v1"
            if isinstance(getattr(answers.answers.model, "broker", None), ExecutionBroker)
            else "unverified"
        )
        agent_mode = (
            "gemini-broker-v1"
            if type(agent.model).__module__ == "youtube_agent.gemini"
            else "unverified"
        )
        self.provider_operations.update(
            answer=answer_mode, analyze=answer_mode, research=agent_mode, artifact=agent_mode
        )
        declared = getattr(type(self), "provider_operations", None)
        if isinstance(declared, dict):
            self.provider_operations = dict(declared)
        self.closed = False

    async def ingest(self, video_id, context):
        return await self.ingestion.ingest(video_id, context)

    async def index(self, *args):
        return await self.answers.index(*args)

    async def delete(self, *args):
        return await self.answers.delete(*args)

    async def evidence(self, *args):
        return await self.answers.evidence(*args)

    async def inventory(self, *args):
        return await self.answers.inventory(*args)

    async def answer(self, *args):
        return await self.answers.answer(*args)

    async def analyze(self, *args):
        return await self.answers.analyze(*args)

    async def research(self, *args):
        return await self.agent.research(*args)

    async def artifact(self, *args):
        return await self.agent.artifact(*args)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self.ingestion.close()
        finally:
            try:
                await self.agent.model.close()
            finally:
                await self.answers.close()


async def create_adapters(*, settings, repository):
    try:
        from youtube_agent.gemini import GeminiModel as AgentModel
        from youtube_agent.service import AgentService
        from youtube_ingestion.service import IngestionService
    except ImportError:
        raise error(
            "integration_not_installed", "Install module 05 with --extra team", status=503
        ) from None
    config = load_team_configuration(settings)
    gateway = GeminiModel(config.answers, broker=ExecutionBroker(repository, config.answers))
    try:
        answers = AnswerAdapters(
            settings=settings,
            repository=repository,
            answer_settings=config.answers,
            model=gateway,
            rag_settings=config.rag,
        )
    except BaseException:
        await gateway.close()
        raise
    ingestion, agent_model = None, None
    try:
        ingestion = IngestionService(config.ingestion)
        agent_model = AgentModel(config.agent)
        from .video import NativeVideoAnswers, needs_video
        native = NativeVideoAnswers(gateway, config.answers)
        agent = AgentService(
            config.agent, agent_model, RagKnowledge(answers.rag), analyzer=answers.analyze,
            media_answerer=native.answer, media_selector=needs_video,
        )
        return TeamAdapters(answers, ingestion, agent)
    except BaseException:
        try:
            if ingestion is not None:
                await ingestion.close()
        finally:
            try:
                if agent_model is not None:
                    await agent_model.close()
            finally:
                await answers.close()
        raise
