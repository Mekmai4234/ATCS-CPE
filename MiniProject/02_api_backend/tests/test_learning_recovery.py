import pytest
from conftest import VIDEO_A, import_ready

from youtube_backend.errors import AppError


def test_general_chat_has_no_video_claims_and_is_saved(env):
    response = env.client.post("/api/chat", json={"question": "ทำอะไรอยู่", "mode": "general"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["citations"] == [] and data["assistant_message_id"]
    history = env.client.get("/api/conversations/" + data["conversation_id"]).json()
    assert history["scope"] is None
    assert len(history["messages"]) == 2
    assert env.client.post("/api/chat", json={"question": "clip?"}).status_code == 422
    assert (
        env.client.post(
            "/api/chat",
            json={"question": "clip?", "mode": "general", "scope": {"video_ids": [VIDEO_A]}},
        ).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_quiz_submission_uses_saved_answers_and_replays(env):
    await import_ready(env, VIDEO_A)
    job = env.repo.enqueue("artifact", {"type": "quiz", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(job["job_id"])
    artifact = env.repo.get_job(job["job_id"])["result"]["artifact_ids"][0]
    path = "/api/learning-artifacts/" + artifact + "/submit"
    first = env.client.post(
        path, json={"answers": ["wrong"]}, headers={"Idempotency-Key": "quiz-test"}
    )
    assert first.status_code == 202, first.text
    await env.worker.run_once(first.json()["job_id"])
    result = env.repo.get_job(first.json()["job_id"])["result"]
    assert result["total"] == 1 and result["correct"] == 0
    assert result["marks"][0]["correct"] is False
    assert (
        env.client.post(
            path, json={"answers": ["wrong"]}, headers={"Idempotency-Key": "quiz-test"}
        ).json()["job_id"]
        == first.json()["job_id"]
    )
    assert env.client.post(path, json={"answers": []}).status_code == 422
    assert env.client.post(path, json={"answers": ["correct"], "questions": []}).status_code == 422
    assert (
        env.client.post(
            "/api/learning-artifacts/foreign/submit", json={"answers": ["x"]}
        ).status_code
        == 404
    )


@pytest.mark.asyncio
async def test_long_quota_wait_parks_import_without_marking_video_failed(env):
    item = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
    job = env.repo.claim(item["job_id"])
    env.repo.fail(
        job["job_id"],
        job["lease_token"],
        AppError(
            "quota_wait", "wait", 429, True, retry_after_seconds=3600, retry_time_source="estimate"
        ),
    )
    saved = env.repo.get_job(job["job_id"])
    assert saved["state"] == "paused"
    video = env.repo.list_videos(50, 0)["items"][0]
    assert video["import_job"]["error_code"] == "quota_wait"
    assert video["import_job"]["retryable"] is True
    assert env.repo.public_job(saved)["wait"]["reason"] == "quota_wait"
    replacement = env.repo.retry(job["job_id"])
    assert replacement["state"] == "queued" and replacement["job_id"] != job["job_id"]


def test_quota_paused_chat_returns_a_durable_accepted_job(env):
    async def unavailable(*args):
        raise AppError(
            "quota_wait",
            "daily limit",
            429,
            True,
            retry_after_seconds=3600,
            retry_time_source="estimate",
        )

    env.adapters.companion = unavailable
    response = env.client.post("/api/chat", json={"question": "ทำอะไรอยู่", "mode": "general"})
    assert response.status_code == 202, response.text
    assert env.repo.get_job(response.json()["job_id"])["state"] == "paused"


@pytest.mark.asyncio
async def test_index_retry_reuses_transcript_instead_of_fetching_youtube_again(env):
    original = env.adapters.index

    async def unavailable(*args):
        raise AppError("quota_wait", "index budget", 429, True, retry_after_seconds=3600)

    env.adapters.index = unavailable
    item = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
    await env.worker.run_once(item["job_id"])
    assert env.repo.get_job(item["job_id"])["state"] == "paused"

    async def must_not_ingest(*args):
        raise AssertionError("captions already fetched; do not fetch twice")

    env.adapters.ingest = must_not_ingest
    env.adapters.index = original
    replacement = env.repo.retry(item["job_id"])
    await env.worker.run_once(replacement["job_id"])
    assert env.repo.get_job(replacement["job_id"])["state"] == "completed"
    assert env.repo.list_videos(50, 0)["items"][0]["status"] == "ready"


@pytest.mark.asyncio
async def test_blank_quiz_answer_cannot_receive_credit_from_a_bad_grader(env):
    await import_ready(env, VIDEO_A)
    quiz = env.repo.enqueue("artifact", {"type": "quiz", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(quiz["job_id"])
    artifact = env.repo.get_job(quiz["job_id"])["result"]["artifact_ids"][0]

    async def bad_grader(*args):
        return {"marks": [{"correct": True, "feedback": "bad fixture"}]}

    env.adapters.grade_quiz = bad_grader
    job = env.repo.enqueue_quiz(artifact, [""])
    await env.worker.run_once(job["job_id"])
    result = env.repo.get_job(job["job_id"])["result"]
    assert result["correct"] == 0 and result["marks"][0]["correct"] is False
