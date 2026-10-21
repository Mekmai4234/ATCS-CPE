import asyncio
from types import SimpleNamespace

import pytest
from conftest import VIDEO_A, VIDEO_B, track
from member_backend_double import MemberBackendDouble
from youtube_backend.errors import AppError
from youtube_backend.schemas import Source

from youtube_ingestion.member_adapters import MemberSourceAdapters
from youtube_ingestion.members import MemberIngestion, MemberSettings, SourceCommand, SourceGrant
from youtube_ingestion.models import Metadata
from youtube_ingestion.service import IngestionService


class Inner:
    def __init__(self):
        self.calls = []
        self.delay = 0
        self.started = asyncio.Event()

    async def _call(self, operation, *args):
        self.calls.append((operation, args))
        self.started.set()
        await asyncio.sleep(self.delay)
        args[-1].check()
        return operation

    async def ingest(self, *args):
        return await self._call("ingest", *args)

    async def index(self, *args):
        return await self._call("index", *args)

    async def delete(self, *args):
        return await self._call("delete", *args)

    async def evidence(self, *args):
        return await self._call("evidence", *args)

    async def inventory(self, *args):
        return await self._call("inventory", *args)

    async def close(self):
        self.calls.append(("close", ()))


def environment():
    backend = MemberBackendDouble()
    service = MemberIngestion(backend, MemberSettings(_env_file=None))
    for context in (backend.a, backend.b):
        service.add({"urls": [f"https://youtu.be/{VIDEO_A}"]}, context)
    inner = Inner()
    return backend, service, inner, MemberSourceAdapters(inner, backend)


async def test_member_cannot_run_shared_import_or_physical_gc():
    backend, _, inner, adapters = environment()
    for call in [
        lambda: adapters.ingest(VIDEO_A, backend.a),
        lambda: adapters.delete(VIDEO_A, 1, backend.a),
    ]:
        with pytest.raises(AppError) as error:
            await call()
        assert error.value.status_code == 403
    assert not inner.calls
    assert await adapters.ingest(VIDEO_A, backend) == "ingest"


async def test_a_remove_does_not_cancel_b_import_and_gc_waits_for_refs_and_jobs():
    backend, service, inner, adapters = environment()
    service.remove(VIDEO_A, backend.a)
    assert await adapters.ingest(VIDEO_A, backend) == "ingest"
    with pytest.raises(AppError, match="in use"):
        await adapters.delete(VIDEO_A, 1, backend)
    service.remove(VIDEO_A, backend.b)
    with pytest.raises(AppError, match="in use"):
        await adapters.delete(VIDEO_A, 1, backend)
    backend.finish(VIDEO_A)
    assert await adapters.delete(VIDEO_A, 1, backend) == "delete"
    backend.sources[VIDEO_A]["generation"] = 2
    with pytest.raises(AppError):
        await adapters.delete(VIDEO_A, 1, backend)


async def test_reader_needs_membership_and_exact_version_even_with_known_chunk_ids():
    backend, service, inner, adapters = environment()
    backend.finish(VIDEO_A)
    source = Source(video_id=VIDEO_A, generation=1, transcript_version="v1")
    assert await adapters.evidence([source], ["known-chunk"], backend.b) == "evidence"
    service.remove(VIDEO_A, backend.a)
    for context in (backend.a, backend.admin):
        with pytest.raises(AppError):
            await adapters.evidence([source], ["known-chunk"], context)
    stale = source.model_copy(update={"transcript_version": "v0"})
    with pytest.raises(AppError):
        await adapters.inventory([stale], backend.b)


async def test_revocation_during_async_read_prevents_returning_result():
    backend, service, inner, adapters = environment()
    backend.finish(VIDEO_A)
    inner.delay = 0.05
    source = Source(video_id=VIDEO_A, generation=1, transcript_version="v1")
    task = asyncio.create_task(adapters.evidence([source], ["known-chunk"], backend.a))
    await inner.started.wait()
    service.remove(VIDEO_A, backend.a)
    with pytest.raises(AppError):
        await task


async def test_generation_change_blocks_index_before_inner_call():
    backend, _, inner, adapters = environment()
    source = Source(video_id=VIDEO_A, generation=1, transcript_version="v1")
    backend.sources[VIDEO_A]["generation"] = 2
    with pytest.raises(AppError):
        await adapters.index(source, track(), backend)
    assert not inner.calls


@pytest.mark.parametrize(
    "grant",
    [
        None,
        "owner=admin",
        SourceGrant(
            SourceCommand(action="gc", video_id=VIDEO_B, generation=1),
            SimpleNamespace(check=lambda: None),
        ),
    ],
)
async def test_mismatched_or_client_shaped_grant_never_reaches_inner(monkeypatch, grant):
    backend, _, inner, adapters = environment()
    monkeypatch.setattr(backend, "authorize_source", lambda *args: grant)
    with pytest.raises(AppError) as error:
        await adapters.ingest(VIDEO_A, backend)
    assert error.value.code == "invalid_source_grant" and not inner.calls


async def test_real_ingestion_cancels_when_shared_authorized_execution_is_revoked(config):
    backend = MemberBackendDouble()
    service = MemberIngestion(backend, MemberSettings(_env_file=None))
    service.add({"urls": [f"https://youtu.be/{VIDEO_A}"]}, backend.a)
    started, stopped = asyncio.Event(), asyncio.Event()

    class Captions:
        async def fetch(self, *args):
            started.set()
            try:
                await asyncio.sleep(10)
                return track()
            finally:
                stopped.set()

        async def close(self):
            pass

    class Meta:
        async def fetch(self, *args):
            return Metadata()

        async def close(self):
            pass

    ingestion = IngestionService(config, captions=Captions(), metadata=Meta())
    inner = SimpleNamespace(ingest=ingestion.ingest, close=ingestion.close)
    adapters = MemberSourceAdapters(inner, backend)
    task = asyncio.create_task(adapters.ingest(VIDEO_A, backend))
    try:
        await started.wait()
        backend.sources[VIDEO_A]["active"] = False
        with pytest.raises(AppError, match="unavailable"):
            await asyncio.wait_for(task, 1)
        assert stopped.is_set()
    finally:
        await adapters.close()
