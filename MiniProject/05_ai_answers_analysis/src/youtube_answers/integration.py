"""05-owned composition of 02/04 boundaries, without changing other modules."""

from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import BackendExecution

from .config import AnswerSettings
from .configuration import resolved_service
from .gemini import GeminiModel
from .service import AnswerService


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
        execution = BackendExecution(context)
        # Whole-video analysis can honestly return partial coverage when an index is missing.
        # 04's evidence() requires ALL supplied indexes; limit this lookup to those available.
        page = await self.rag.read_video_chunks(sources, execution, limit=1)
        missing = {s.video_id for s in page.inventory.missing_sources}
        available = [s for s in sources if s.video_id not in missing]
        if not available:
            return []
        return await self.rag.evidence(available, ids, execution)


class AnswerAdapters(RagAdapters):
    def __init__(
        self,
        *,
        settings,
        repository,
        answer_settings=None,
        model=None,
        rag_settings=None,
        embedder=None,
    ):
        config = answer_settings or AnswerSettings()
        gateway = model or GeminiModel(config)
        super().__init__(
            settings=settings, repository=repository, rag_settings=rag_settings, embedder=embedder
        )
        self.answers = AnswerService(config, gateway, RagKnowledge(self.rag))

    async def answer(self, request, sources, history, context):
        return await self.answers.answer(request, sources, history, context)

    async def analyze(self, request, sources, context):
        return await self.answers.analyze(request, sources, context)

    async def evidence(self, sources, chunk_ids, context):
        return await self.answers.knowledge.evidence(sources, chunk_ids, context)

    async def close(self):
        try:
            await self.answers.model.close()
        finally:
            await super().close()


async def create_adapters(*, settings, repository):
    from youtube_rag.config import RagSettings

    config = resolved_service(settings, AnswerSettings)
    rag_config = resolved_service(settings, RagSettings)
    gateway = GeminiModel(config)
    try:
        return AnswerAdapters(
            settings=settings,
            repository=repository,
            answer_settings=config,
            model=gateway,
            rag_settings=rag_config,
        )
    except BaseException:
        await gateway.close()
        raise
