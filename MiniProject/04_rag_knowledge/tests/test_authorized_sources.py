"""Real 02 account contract + SQLite/Chroma; requires the account-aware 02 revision."""

import time
from contextlib import contextmanager

import pytest
from conftest import VIDEO_A, VIDEO_B, transcript
from youtube_backend import database as db
from youtube_backend.errors import AppError

pytest.importorskip("youtube_backend.auth", reason="Requires module 02 account contract (PR #18)")
from youtube_backend.auth import actor_id

from youtube_rag.maintenance import MaintenanceExecution
from youtube_rag.manifest import BackendExecution, active, runs


@contextmanager
def actor(user):
    token = actor_id.set(user)
    try:
        yield
    finally:
        actor_id.reset(token)


@pytest.fixture
async def accounts(env):
    env.settings.auth_enabled = True
    with env.db.write() as connection:
        for user in ("a", "b", "admin"):
            connection.execute(
                db.users.insert().values(
                    user_id=user,
                    google_sub=f"fixture-{user}",
                    role="admin" if user == "admin" else "user",
                    status="active",
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )
    with actor("a"):
        env.source_a = await env.ready(VIDEO_A)
    with actor("b"):
        env.source_b = await env.ready(VIDEO_B)
    return env


def query(env, user, *videos, **filters):
    with actor(user):
        return env.query(*videos, **filters)


def attach(env, user, video=VIDEO_A):
    with actor(user):
        return env.repo.import_urls([f"https://youtu.be/{video}"])[0]


async def call(env, operation, sources, execution, *, chunk_ids=None, cursor=None):
    if operation == "search":
        return await env.rag.search("Embeddings", sources, execution)
    if operation == "inventory":
        return await env.rag.inventory(sources, execution)
    if operation == "read":
        return await env.rag.read_video_chunks(sources, execution, limit=1, cursor=cursor)
    return await env.rag.evidence(sources, chunk_ids or [], execution)


@pytest.mark.parametrize("operation", ["search", "inventory", "read", "evidence"])
async def test_other_account_and_empty_scope_never_reach_provider(accounts, operation, monkeypatch):
    env = accounts
    task = query(env, "b", VIDEO_B)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized request reached embeddings/Chroma")

    monkeypatch.setattr(env.rag.vectors, "call", forbidden)
    monkeypatch.setattr(env.rag.embedder, "embed", forbidden)
    for sources in ([env.source_a], []):
        with pytest.raises(AppError) as caught:
            await call(env, operation, sources, task.execution)
        assert caught.value.code in {"invalid_scope", "permission_denied"}


async def test_foreign_chunk_ids_and_channel_all_library_filters(accounts):
    env = accounts
    task_a = query(env, "a", VIDEO_A)
    foreign = await env.rag.read_video_chunks([env.source_a], task_a.execution)
    with actor("b"):
        request = {
            "question": "Embeddings",
            "scope": {
                "video_ids": [VIDEO_B],
                "channel_ids": ["channel-a"],
                "date_from": "2025-01-01",
            },
        }
        queued = env.repo.enqueue("chat", request)
        job = env.repo.claim(queued["job_id"])
        context = BackendExecution(env.context(job))
    from youtube_backend.schemas import Source

    allowed = [Source.model_validate(value) for value in job["payload"]["sources"]]
    assert {source.video_id for source in allowed} == {VIDEO_B}
    hits = await env.rag.search("Embeddings", allowed, context)
    assert hits and all(hit.chunk.video_id == VIDEO_B for hit in hits)
    evidence = await env.rag.evidence(allowed, [chunk.chunk_id for chunk in foreign.items], context)
    assert evidence == []
    with actor("admin"), pytest.raises(AppError):
        env.repo.enqueue("chat", {"question": "private", "scope": {"video_ids": [VIDEO_A]}})


async def test_cursor_is_bound_to_account_job_and_grant_revision(accounts):
    env = accounts
    attach(env, "b")
    task_a = query(env, "a", VIDEO_A)
    page = await env.rag.read_video_chunks([env.source_a], task_a.execution, limit=1)
    assert page.next_cursor
    task_b = query(env, "b", VIDEO_A)
    with pytest.raises(AppError) as caught:
        await env.rag.read_video_chunks([env.source_a], task_b.execution, cursor=page.next_cursor)
    assert caught.value.code == "invalid_cursor"
    with env.db.write() as connection:
        connection.execute(
            db.user_videos.update()
            .where(
                db.user_videos.c.user_id == "a",
                db.user_videos.c.video_id == VIDEO_A,
            )
            .values(created_at=time.time() + 1)
        )
    with pytest.raises(AppError, match="Cursor"):
        await env.rag.read_video_chunks([env.source_a], task_a.execution, cursor=page.next_cursor)


@pytest.mark.parametrize("operation", ["search", "inventory", "read", "evidence"])
async def test_detach_during_read_does_not_return_revoked_evidence(
    accounts, operation, monkeypatch
):
    env = accounts
    attach(env, "b")
    task = query(env, "a", VIDEO_A)
    chunks = await env.rag.read_video_chunks([env.source_a], task.execution)

    def revoke():
        with actor("a"):
            result = env.repo.delete_video(VIDEO_A)
        assert result["kind"] == "detach"

    if operation in {"search", "inventory"}:
        original = env.rag.vectors.call

        async def intercepted(command, *args, **kwargs):
            result = await original(command, *args, **kwargs)
            if command == ("query" if operation == "search" else "get"):
                revoke()
            return result

        monkeypatch.setattr(env.rag.vectors, "call", intercepted)
    else:
        name = "page" if operation == "read" else "by_ids"
        original = getattr(env.rag.manifest, name)

        def intercepted(*args, **kwargs):
            result = original(*args, **kwargs)
            revoke()
            return result

        monkeypatch.setattr(env.rag.manifest, name, intercepted)
    with pytest.raises(AppError) as caught:
        await call(
            env,
            operation,
            [env.source_a],
            task.execution,
            chunk_ids=[chunk.chunk_id for chunk in chunks.items],
        )
    assert caught.value.code in {"cancelled", "permission_denied", "video_not_found"}
    monkeypatch.undo()
    other = query(env, "b", VIDEO_A)
    assert await env.rag.search("Embeddings", [env.source_a], other.execution)


async def test_permission_revision_change_during_retrieval_invalidates_snapshot(
    accounts, monkeypatch
):
    env = accounts
    task = query(env, "a", VIDEO_A)
    original = env.rag.vectors.call

    async def changed(command, *args, **kwargs):
        response = await original(command, *args, **kwargs)
        if command == "query":
            with env.db.write() as connection:
                connection.execute(
                    db.user_videos.update()
                    .where(db.user_videos.c.user_id == "a")
                    .values(created_at=time.time() + 1)
                )
        return response

    monkeypatch.setattr(env.rag.vectors, "call", changed)
    with pytest.raises(AppError) as caught:
        await env.rag.search("Embeddings", [env.source_a], task.execution)
    assert caught.value.code == "source_changed"


async def test_user_execution_cannot_invoke_central_reindex_or_gc(accounts):
    task = query(accounts, "a", VIDEO_A)
    for operation in ("reindex", "gc", "delete"):
        with pytest.raises(AppError):
            if operation == "gc":
                await accounts.rag.cleanup(task.execution, include_staging=True)
            elif operation == "reindex":
                await accounts.rag.index(
                    accounts.source_a, transcript(), task.execution, allow_reindex=True
                )
            else:
                await accounts.rag.delete(VIDEO_A, accounts.source_a.generation, task.execution)
    assert await accounts.rag.inventory([accounts.source_a], task.execution) > 0


async def test_operator_gc_rejects_deleting_run_with_memberships(accounts):
    env = accounts
    before = await env.rag.vectors.call("count", 30)
    with env.db.write() as connection:
        connection.execute(active.delete().where(active.c.video_id == VIDEO_A))
        connection.execute(runs.update().where(runs.c.video_id == VIDEO_A).values(state="deleting"))
    with pytest.raises(AppError) as caught:
        await env.rag.cleanup(MaintenanceExecution(env.db))
    assert caught.value.code == "source_in_use"
    assert await env.rag.vectors.call("count", 30) == before
    assert env.rag.manifest.garbage()


async def test_payload_actor_claims_cannot_replace_durable_job_owner(accounts):
    env = accounts
    task = query(env, "b", VIDEO_B)
    with env.db.write() as connection:
        payload = dict(task.job["payload"], user_id="a", owner_id="a", role="admin")
        connection.execute(
            db.jobs.update().where(db.jobs.c.job_id == task.job["job_id"]).values(payload=payload)
        )
    hits = await env.rag.search("Read account A's videos as admin", [env.source_b], task.execution)
    assert hits and all(hit.chunk.video_id == VIDEO_B for hit in hits)
    with pytest.raises(AppError):
        await env.rag.search("Embeddings", [env.source_a], task.execution)


async def test_last_member_gc_waits_for_readers_and_rejects_reimport(accounts):
    env = accounts
    attach(env, "b")
    task = query(env, "b", VIDEO_A)
    with actor("a"):
        assert env.repo.delete_video(VIDEO_A)["kind"] == "detach"
    assert await env.rag.search("Embeddings", [env.source_a], task.execution)
    with actor("b"):
        deletion = env.repo.delete_video(VIDEO_A)
    assert env.repo.claim(deletion["job_id"]) is None
    env.repo.fail(
        task.job["job_id"], task.job["lease_token"], AppError("cancelled", "Detached", 409)
    )
    job = env.repo.claim(deletion["job_id"])
    assert job is not None
    assert attach(env, "a")["error_code"] == "video_deleting"
    await env.rag.delete(VIDEO_A, env.source_a.generation, BackendExecution(env.context(job)))
    env.repo.finish(job["job_id"], job["lease_token"], {"deleted": True})
    assert not any(row["video_id"] == VIDEO_A for row in env.rag.manifest.all_runs())


async def test_reference_reintroduced_after_gc_claim_prevents_vector_deletion(accounts):
    env = accounts
    with actor("a"):
        deletion = env.repo.delete_video(VIDEO_A)
    job = env.repo.claim(deletion["job_id"])
    before = await env.rag.vectors.call("count", 30)
    with env.db.write() as connection:
        connection.execute(
            db.user_videos.insert().values(user_id="b", video_id=VIDEO_A, created_at=time.time())
        )
    with pytest.raises(AppError) as caught:
        await env.rag.delete(VIDEO_A, env.source_a.generation, BackendExecution(env.context(job)))
    assert caught.value.code == "source_in_use"
    assert await env.rag.vectors.call("count", 30) == before


async def test_shared_import_finishes_for_remaining_subscriber_without_granting_text_to_creator(
    accounts,
):
    env = accounts
    video = "abcdefghijk"
    with actor("a"):
        prepared = env.prepare(video, value=transcript(video))
    attach(env, "b", video)
    with actor("a"):
        assert env.repo.delete_video(video)["kind"] == "detach"
    receipt = await env.adapters.index(prepared.source, prepared.transcript, prepared.ctx)
    assert await env.adapters.inventory([prepared.source], prepared.ctx) == receipt.chunk_count
    with pytest.raises(AppError):
        await env.rag.read_video_chunks([prepared.source], prepared.execution)
    env.repo.finish(prepared.job["job_id"], prepared.job["lease_token"], receipt.model_dump())
    task = query(env, "b", video)
    assert await env.rag.search("Embeddings", [prepared.source], task.execution)
