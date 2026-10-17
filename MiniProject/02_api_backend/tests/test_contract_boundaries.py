import asyncio

import pytest
from conftest import VIDEO_A, VIDEO_B, chat_body, import_ready

from youtube_backend.errors import AppError
from youtube_backend.schemas import ProgressEvent


async def test_incomplete_index_receipt_cannot_publish_ready(env, monkeypatch):
    original = env.adapters.index

    async def wrong_count(*args):
        receipt = await original(*args)
        receipt.chunk_count += 1
        return receipt

    monkeypatch.setattr(env.adapters, "index", wrong_count)
    job = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]["job_id"]
    await env.worker.run_once(job)
    assert env.repo.get_job(job)["error_code"] == "incomplete_index"
    assert env.repo.list_videos(10, 0)["items"][0]["status"] == "failed"


async def test_forged_cross_video_evidence_is_rejected(env, monkeypatch):
    await import_ready(env, VIDEO_A, VIDEO_B)
    original = env.adapters.answer

    async def cross_scope(request, sources, history, context):
        result = await original(request, sources, history, context)
        result.citations[0].video_id = VIDEO_B
        return result

    monkeypatch.setattr(env.adapters, "answer", cross_scope)
    response = env.client.post("/api/chat", json=chat_body(VIDEO_A))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_citation"


async def test_forged_chunk_interval_outside_transcript_is_rejected(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    original_answer, original_evidence = env.adapters.answer, env.adapters.evidence

    async def wrong_time(*args):
        result = await original_answer(*args)
        result.citations[0].end_seconds = 9000
        return result

    async def wrong_evidence(*args):
        records = await original_evidence(*args)
        records[0].end_seconds = 9000
        return records

    monkeypatch.setattr(env.adapters, "answer", wrong_time)
    monkeypatch.setattr(env.adapters, "evidence", wrong_evidence)
    assert (
        env.client.post("/api/chat", json=chat_body()).json()["error"]["code"] == "invalid_citation"
    )


async def test_model_urls_replaced_by_canonical_sources(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    original = env.adapters.answer

    async def url_injection(*args):
        result = await original(*args)
        result.citations[0].url = "https://untrusted.example"
        result.citations[0].title = "fabricated title"
        return result

    monkeypatch.setattr(env.adapters, "answer", url_injection)
    response = env.client.post("/api/chat", json=chat_body())
    assert response.status_code == 200
    assert response.json()["citations"][0]["url"].startswith("https://www.youtube.com/watch?")
    assert response.json()["citations"][0]["title"].startswith("[FIXTURE]")


async def test_wrong_coverage_counts_rejected(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    original = env.adapters.analyze

    async def wrong(*args):
        result = await original(*args)
        result.coverage.expected_chunks = 900
        result.coverage.processed_chunks = 900
        return result

    monkeypatch.setattr(env.adapters, "analyze", wrong)
    job = env.repo.enqueue("analysis", {"type": "summary", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(job["job_id"])
    assert env.repo.get_job(job["job_id"])["error_code"] == "invalid_coverage"


async def test_partial_research_is_persisted_without_claiming_completion(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    original = env.adapters.research

    async def partial(*args):
        result = await original(*args)
        result.state = "partial"
        result.coverage.complete = False
        result.coverage.processed_chunks = 1
        result.coverage.notes = ["Stopped before deadline; some findings are missing"]
        return result

    monkeypatch.setattr(env.adapters, "research", partial)
    job = env.repo.enqueue("research", {"goal": "RAG", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(job["job_id"])
    result = env.repo.get_job(job["job_id"])
    assert result["state"] == "partial"
    assert result["result"]["coverage"]["processed_chunks"] == 1
    assert result["result"]["artifact_ids"]


async def test_event_step_budget_is_enforced(env, monkeypatch):
    await import_ready(env, VIDEO_A)

    async def excessive(request, sources, context):
        context.event(
            ProgressEvent(
                step=env.settings.agent_max_steps + 1,
                tool_name="read",
                state="running",
                summary="Exceeds budget",
            )
        )

    monkeypatch.setattr(env.adapters, "research", excessive)
    job = env.repo.enqueue("research", {"goal": "RAG", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(job["job_id"])
    assert env.repo.get_job(job["job_id"])["error_code"] == "agent_budget_exceeded"
    assert not env.repo.list_events(job["job_id"])


async def test_artifact_requires_explanation_and_valid_item_citations(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    original = env.adapters.artifact

    async def invalid(request, sources, context):
        result = await original(request, sources, context)
        data = result.model_dump()
        data["content"]["questions"][0]["citations"] = ["unknown"]
        return data

    monkeypatch.setattr(env.adapters, "artifact", invalid)
    job = env.repo.enqueue("artifact", {"type": "quiz", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(job["job_id"])
    assert env.repo.get_job(job["job_id"])["error_code"] == "adapter_invalid_output"
    with env.db.read() as connection:
        from sqlalchemy import func, select

        from youtube_backend.database import artifacts

        assert connection.scalar(select(func.count()).select_from(artifacts)) == 0


def test_replay_marks_deleted_sources_unavailable(ready):
    response = ready.client.post("/api/chat", json=chat_body(), headers={"Idempotency-Key": "old"})
    data = response.json()
    ready.client.delete(f"/api/videos/{VIDEO_A}")
    replay = ready.client.post("/api/chat", json=chat_body(), headers={"Idempotency-Key": "old"})
    assert replay.status_code == 200
    assert replay.json()["answer"] == data["answer"]
    assert not replay.json()["sources_available"]
    job = ready.client.get(f"/api/jobs/{data['job_id']}").json()
    assert not job["sources_available"]


async def test_http_chat_202_can_be_recovered_by_worker(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    original = env.adapters.answer
    calls = 0

    async def temporarily_unavailable(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AppError("provider_quota", "Retry later", 503, True)
        return await original(*args)

    monkeypatch.setattr(env.adapters, "answer", temporarily_unavailable)
    response = env.client.post(
        "/api/chat", json=chat_body(), headers={"Idempotency-Key": "recover"}
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    await env.worker.run_once(job_id)
    result = env.client.get(f"/api/jobs/{job_id}").json()
    assert result["state"] == "completed"
    replay = env.client.post("/api/chat", json=chat_body(), headers={"Idempotency-Key": "recover"})
    assert replay.status_code == 200
    assert calls == 2


async def test_shutdown_releases_job_for_restart(env, monkeypatch):
    entered = asyncio.Event()
    original = env.adapters.ingest

    async def waiting(*args):
        entered.set()
        await asyncio.sleep(10)
        return await original(*args)

    monkeypatch.setattr(env.adapters, "ingest", waiting)
    job = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]["job_id"]
    running = asyncio.create_task(env.worker.run_once(job))
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert env.repo.get_job(job)["state"] == "queued"
    monkeypatch.setattr(env.adapters, "ingest", original)
    await env.worker.run_once(job)
    assert env.repo.get_job(job)["stage"] == "ready"
