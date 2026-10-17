import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B, chat_body, import_ready

from youtube_backend import database as db
from youtube_backend.database import Database
from youtube_backend.errors import AppError, LeaseLost
from youtube_backend.fixture_adapter import FixtureAdapters
from youtube_backend.repository import Repository
from youtube_backend.schemas import ProgressEvent
from youtube_backend.worker import Worker


def queue_import(env, video_id=VIDEO_A):
    return env.repo.import_urls([f"https://youtu.be/{video_id}"])[0]["job_id"]


def expire(env, job_id):
    with env.db.write() as connection:
        connection.execute(
            db.jobs.update().where(db.jobs.c.job_id == job_id).values(lease_until=time.time() - 1)
        )


async def test_missing_captions_unavailable_and_transient_retry(env):
    missing = queue_import(env, "NoCaption01")
    await env.worker.run_once(missing)
    assert env.repo.get_job(missing)["stage"] == "no_transcript"
    unavailable = queue_import(env, "Unavailable")
    await env.worker.run_once(unavailable)
    assert env.repo.get_job(unavailable)["error_code"] == "video_unavailable"
    retry = queue_import(env, "RetryOnce01")
    await env.worker.run_once(retry)
    assert env.repo.get_job(retry)["state"] == "queued"
    await env.worker.run_once(retry)
    assert env.repo.get_job(retry)["stage"] == "ready"
    assert env.repo.get_job(retry)["attempt_count"] == 2
    assert env.repo.transcript("RetryOnce01", 100, 0)["total"] == 3


async def test_backoff_waits_until_due_without_resetting_deadline(env):
    env.settings.job_retry_base_seconds = 30
    job_id = queue_import(env, "RetryOnce01")
    await env.worker.run_once(job_id)
    first = env.repo.get_job(job_id)
    assert first["available_at"] > time.time() + 28
    assert not await env.worker.run_once(job_id)
    with env.db.write() as connection:
        connection.execute(
            db.jobs.update().where(db.jobs.c.job_id == job_id).values(available_at=time.time() - 1)
        )
    await env.worker.run_once(job_id)
    second = env.repo.get_job(job_id)
    assert second["deadline_at"] == first["deadline_at"]
    assert second["stage"] == "ready" and second["attempt_count"] == 2


async def test_caption_import_succeeds_without_optional_metadata(env, monkeypatch):
    original = env.adapters.ingest

    async def no_metadata(*args):
        transcript = await original(*args)
        transcript.title = None
        transcript.channel_id = None
        transcript.published_at = None
        return transcript

    monkeypatch.setattr(env.adapters, "ingest", no_metadata)
    await import_ready(env, VIDEO_A)
    transcript = env.client.get(f"/api/videos/{VIDEO_A}/transcript").json()
    assert transcript["segments"][0]["language"] == "th"
    assert transcript["segments"][0]["transcript_version"] == transcript["transcript_version"]
    answer = env.client.post("/api/chat", json=chat_body())
    assert answer.status_code == 200
    assert answer.json()["citations"][0]["title"] == f"YouTube {VIDEO_A}"


async def test_restart_recovery_rejects_stale_execution(env):
    job_id = queue_import(env)
    old = env.repo.claim(job_id)
    assert env.repo.claim(job_id) is None
    expire(env, job_id)
    restarted_db = Database(env.settings.database_url)
    repo = Repository(restarted_db, env.settings)
    worker = Worker(repo, FixtureAdapters(repo, env.settings), env.settings)
    await worker.run_once(job_id)
    assert repo.get_job(job_id)["stage"] == "ready"
    assert repo.get_job(job_id)["attempt_count"] == 2
    with pytest.raises(LeaseLost):
        env.repo.finish(job_id, old["lease_token"])
    assert env.repo.transcript(VIDEO_A, 100, 0)["total"] == 3
    with env.db.read() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(db.fixture_chunks)) == 3
    restarted_db.close()


def test_claim_atomic_across_worker_connections(env):
    job_id = queue_import(env)

    def claim(_):
        database = Database(env.settings.database_url)
        try:
            return Repository(database, env.settings).claim(job_id)
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(claim, range(8)))
    assert sum(c is not None for c in claims) == 1


async def test_heartbeat_prevents_reclaim_of_slow_operation(env, monkeypatch):
    env.settings.job_lease_seconds = 0.3
    original = env.adapters.ingest
    entered = asyncio.Event()

    async def slow(video_id, context):
        entered.set()
        await asyncio.sleep(0.7)
        return await original(video_id, context)

    monkeypatch.setattr(env.adapters, "ingest", slow)
    job_id = queue_import(env)
    running = asyncio.create_task(env.worker.run_once(job_id))
    await entered.wait()
    await asyncio.sleep(0.4)
    assert env.repo.claim(job_id) is None
    await running
    assert env.repo.get_job(job_id)["stage"] == "ready"
    assert env.repo.get_job(job_id)["attempt_count"] == 1


async def test_index_failure_never_marks_ready_and_retries_idempotently(env, monkeypatch):
    original = env.adapters.index

    async def fail_once(source, transcript, context):
        await original(source, transcript, context)
        if env.repo.get_job(context.job_id)["attempt_count"] == 1:
            raise AppError("embedding_timeout", "Temporary index problem", 504, True)
        return await original(source, transcript, context)

    monkeypatch.setattr(env.adapters, "index", fail_once)
    job_id = queue_import(env)
    await env.worker.run_once(job_id)
    assert env.repo.list_videos(10, 0)["items"][0]["status"] == "queued"
    await env.worker.run_once(job_id)
    assert env.repo.get_job(job_id)["stage"] == "ready"
    with env.db.read() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(db.segments)) == 3
        assert connection.scalar(sa.select(sa.func.count()).select_from(db.fixture_chunks)) == 3


async def test_bounded_retries_and_manual_retry(env, monkeypatch):
    async def failing(*args):
        raise AppError("provider_quota", "Temporary quota limit", 503, True)

    monkeypatch.setattr(env.adapters, "ingest", failing)
    job_id = queue_import(env)
    for _ in range(4):
        await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "failed" and job["attempt_count"] == 3
    retry = env.client.post(f"/api/jobs/{job_id}/retry")
    assert retry.status_code == 202
    assert retry.json()["job_id"] != job_id
    assert env.client.post(f"/api/jobs/{job_id}/retry").json()["job_id"] == retry.json()["job_id"]


async def test_timeout_cancels_adapter_and_preserves_deadline(env, monkeypatch):
    env.settings.job_timeout_seconds = 0.05
    cancelled = asyncio.Event()

    async def slow(*args):
        try:
            await asyncio.sleep(2)
        finally:
            cancelled.set()

    monkeypatch.setattr(env.adapters, "ingest", slow)
    job_id = queue_import(env)
    await env.worker.run_once(job_id)
    assert cancelled.is_set()
    result = env.repo.get_job(job_id)
    assert result["error_code"] == "task_timeout"
    assert result["state"] == "failed"
    assert result["attempt_count"] == 1


async def test_delete_during_index_waits_and_does_not_resurrect(env, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    original = env.adapters.index

    async def slow_index(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(env.adapters, "index", slow_index)
    job_id = queue_import(env)
    running = asyncio.create_task(env.worker.run_once(job_id))
    await entered.wait()
    deletion = env.repo.delete_video(VIDEO_A)
    assert env.repo.claim(deletion["job_id"]) is None
    assert env.client.get("/api/videos").json()["total"] == 0
    release.set()
    await running
    assert env.repo.get_job(job_id)["state"] == "cancelled"
    await env.worker.run_once(deletion["job_id"])
    assert env.repo.get_job(deletion["job_id"])["state"] == "completed"
    assert env.client.get(f"/api/videos/{VIDEO_A}/transcript").status_code == 404
    with env.db.read() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(db.fixture_chunks)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(db.segments)) == 0


async def test_deletion_retry_reimport_generation_and_history(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    chat = env.client.post("/api/chat", json=chat_body()).json()
    original = env.adapters.delete

    async def fail_once(*args):
        context = args[-1]
        if env.repo.get_job(context.job_id)["attempt_count"] == 1:
            raise AppError("delete_timeout", "Temporary deletion problem", 504, True)
        await original(*args)

    monkeypatch.setattr(env.adapters, "delete", fail_once)
    deletion = env.client.delete(f"/api/videos/{VIDEO_A}").json()["job_id"]
    assert env.client.delete(f"/api/videos/{VIDEO_A}").json()["job_id"] == deletion
    assert env.client.post(f"/api/jobs/{deletion}/cancel").status_code == 409
    assert (
        env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]["error_code"] == "video_deleting"
    )
    await env.worker.run_once(deletion)
    assert env.repo.get_job(deletion)["state"] == "queued"
    await env.worker.run_once(deletion)
    assert env.repo.get_job(deletion)["state"] == "completed"
    await import_ready(env, VIDEO_A)
    assert env.repo.list_videos(10, 0)["items"][0]["generation"] == 2
    history = env.client.get(f"/api/conversations/{chat['conversation_id']}").json()
    assert not history["messages"][1]["citations"][0]["source_available"]


async def test_cancel_running_research_without_resetting_budget(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    entered = asyncio.Event()

    async def research(request, sources, context):
        context.event(ProgressEvent(step=1, tool_name="read", state="running", summary="Reading"))
        entered.set()
        await asyncio.sleep(4)

    monkeypatch.setattr(env.adapters, "research", research)
    job = env.repo.enqueue("research", {"goal": "RAG", "scope": {"video_ids": [VIDEO_A]}})
    running = asyncio.create_task(env.worker.run_once(job["job_id"]))
    await entered.wait()
    env.repo.cancel(job["job_id"])
    await running
    result = env.repo.get_job(job["job_id"])
    assert result["state"] == "cancelled"
    assert result["attempt_count"] == 1
    assert len(env.repo.list_events(job["job_id"])) == 1


async def test_research_crash_does_not_replay_agent(env):
    await import_ready(env, VIDEO_A)
    job = env.repo.enqueue("research", {"goal": "RAG", "scope": {"video_ids": [VIDEO_A]}})
    claimed = env.repo.claim(job["job_id"])
    deadline = claimed["deadline_at"]
    expire(env, job["job_id"])
    assert env.repo.claim(job["job_id"]) is None
    failed = env.repo.get_job(job["job_id"])
    assert failed["state"] == "failed" and failed["error_code"] == "worker_interrupted"
    assert failed["deadline_at"] == deadline and failed["attempt_count"] == 1


async def test_scope_change_before_result_prevents_publication(env, monkeypatch):
    await import_ready(env, VIDEO_A, VIDEO_B)
    original = env.adapters.analyze

    async def delete_source(request, sources, context):
        result = await original(request, sources, context)
        env.repo.delete_video(VIDEO_A)
        return result

    monkeypatch.setattr(env.adapters, "analyze", delete_source)
    job = env.repo.enqueue(
        "analysis", {"type": "compare", "scope": {"video_ids": [VIDEO_A, VIDEO_B]}}
    )
    await env.worker.run_once(job["job_id"])
    assert env.repo.get_job(job["job_id"])["state"] == "cancelled"
    assert env.repo.get_job(job["job_id"])["result"] is None


async def test_invalid_citation_and_invalid_output_rejected(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    original = env.adapters.answer

    async def bogus(*args):
        result = await original(*args)
        result.citations[0].start_seconds = 9999
        return result

    monkeypatch.setattr(env.adapters, "answer", bogus)
    response = env.client.post("/api/chat", json=chat_body())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_citation"
    job_id = response.json()["error"]["job_id"]
    conversation_id = env.repo.get_job(job_id)["conversation_id"]
    assert env.repo.conversation(conversation_id, 100, 0)["total"] == 1

    async def invalid(*args):
        return {"answer": "bad shape"}

    monkeypatch.setattr(env.adapters, "answer", invalid)
    response = env.client.post("/api/chat", json=chat_body())
    assert response.json()["error"]["code"] == "adapter_invalid_output"


async def test_provider_exception_does_not_leak_secret(env, monkeypatch, caplog):
    await import_ready(env, VIDEO_A)

    async def explode(*args):
        raise RuntimeError("https://provider.invalid?key=TOP_SECRET_TEST")

    monkeypatch.setattr(env.adapters, "answer", explode)
    response = env.client.post("/api/chat", json=chat_body())
    assert response.status_code == 502
    assert "TOP_SECRET_TEST" not in response.text
    assert "TOP_SECRET_TEST" not in caplog.text
