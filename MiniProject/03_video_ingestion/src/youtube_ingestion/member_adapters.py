"""Opt-in shared worker/read guard. Not wired into the single-user HTTP API."""

from youtube_backend.integrations import UnavailableAdapters
from youtube_backend.schemas import Source

from .errors import failure
from .integration import create_adapters
from .members import SourceCommand, SourceGrant, require_backend


class MemberSourceAdapters(UnavailableAdapters):
    capabilities = dict.fromkeys(("ingest", "index", "delete", "evidence", "inventory"), True)

    def __init__(self, inner, backend):
        self.backend = require_backend(backend)
        self.inner = inner

    async def _call(self, name, args, context, command):
        expected = command.model_dump(mode="json")
        grant = self.backend.authorize_source(context, command)
        if (
            not isinstance(grant, SourceGrant)
            or not isinstance(grant.command, SourceCommand)
            or grant.command.model_dump(mode="json") != expected
            or not callable(getattr(grant.execution, "check", None))
        ):
            raise failure(
                "invalid_source_grant", "Backend did not authorize this source operation", 403
            )
        grant.execution.check()
        value = await getattr(self.inner, name)(*args, grant.execution)
        grant.execution.check()
        if grant.command.model_dump(mode="json") != expected:
            raise failure(
                "invalid_source_grant", "Source authorization changed during execution", 403
            )
        return value

    async def ingest(self, video_id, context):
        from .members import MemberIngestion

        MemberIngestion._video_id(video_id)
        return await self._call(
            "ingest", (video_id,), context, SourceCommand(action="ingest", video_id=video_id)
        )

    async def index(self, source, transcript, context):
        source = Source.model_validate(source).model_copy(deep=True)
        return await self._call(
            "index",
            (source, transcript),
            context,
            SourceCommand(
                action="index",
                video_id=source.video_id,
                generation=source.generation,
                sources=(source,),
            ),
        )

    async def delete(self, video_id, generation, context):
        from .members import MemberIngestion

        MemberIngestion._video_id(video_id)
        # This is physical GC, never a member's remove-from-library request.
        if type(generation) is not int or generation < 1:
            raise failure("invalid_generation", "Provide a positive source generation", 422)
        return await self._call(
            "delete",
            (video_id, generation),
            context,
            SourceCommand(action="gc", video_id=video_id, generation=generation),
        )

    async def evidence(self, sources, chunk_ids, context):
        sources = self._sources(sources)
        return await self._call(
            "evidence",
            (sources, chunk_ids),
            context,
            SourceCommand(action="read", sources=tuple(sources)),
        )

    async def inventory(self, sources, context):
        sources = self._sources(sources)
        return await self._call(
            "inventory", (sources,), context, SourceCommand(action="read", sources=tuple(sources))
        )

    @staticmethod
    def _sources(sources):
        from .members import MemberIngestion

        sources = [Source.model_validate(s).model_copy(deep=True) for s in sources]
        if not sources or len({s.video_id for s in sources}) != len(sources):
            raise failure("invalid_scope", "Provide distinct authorized sources", 422)
        for source in sources:
            MemberIngestion._video_id(source.video_id)
        return sources

    async def close(self):
        await self.inner.close()


async def create_member_adapters(*, settings, repository):
    # Only trusted server composition can attach this backend. Never load it from JSON
    # or fall back to the globally scoped legacy Repository.
    backend = require_backend(getattr(repository, "member_ingestion_backend", None))
    inner = await create_adapters(settings=settings, repository=repository)
    return MemberSourceAdapters(inner, backend)
