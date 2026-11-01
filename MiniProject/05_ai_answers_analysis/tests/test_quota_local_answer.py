import pytest
from test_integration import integrated as integrated
from youtube_backend.errors import AppError


@pytest.mark.parametrize("reason", ["quota_wait", "provider_unavailable", "generation_timeout"])
async def test_quota_chat_completes_with_authorized_local_evidence(integrated, monkeypatch, reason):
    env = integrated
    calls = []

    async def limited(*args, **kwargs):
        calls.append(True)
        raise AppError(reason, "Fixture admission failure", 503, True)

    monkeypatch.setattr(env.answers, "_answer_provider", limited)
    body = {"question": "RAG", "scope": {"video_ids": ["dQw4w9WgXcQ"]}}
    response = await env.client.post("/api/chat", json=body)
    await env.worker.run_once(response.json()["job_id"])
    job = env.repo.get_job(response.json()["job_id"])
    assert job["state"] == "completed", job["error_code"]
    result = job["result"]
    assert result["provider_metadata"]["provider"] == "local-evidence"
    assert result["citations"] and all(c["video_id"] == "dQw4w9WgXcQ" for c in result["citations"])
    assert result["coverage"]["complete"] is False
    assert "ไม่ใช่ตัวอย่างหรือคำสรุป" in result["answer"]
    assert len(calls) == 1


async def test_permission_error_is_not_hidden_by_local_fallback(integrated, monkeypatch):
    env = integrated

    async def denied(*args, **kwargs):
        raise AppError("permission_revoked", "Fixture revoked", 403)

    monkeypatch.setattr(env.answers, "_answer_provider", denied)
    response = await env.client.post(
        "/api/chat", json={"question": "RAG", "scope": {"video_ids": ["dQw4w9WgXcQ"]}}
    )
    await env.worker.run_once(response.json()["job_id"])
    job = env.repo.get_job(response.json()["job_id"])
    assert job["state"] == "failed" and job["result"] is None


@pytest.mark.parametrize("integrated", ["youtube_answers.team:create_adapters"], indirect=True)
async def test_existing_paused_clip_chat_resumes_without_requiring_generation_quota(
    integrated, monkeypatch
):
    from youtube_backend import job_resume

    env = integrated

    body = {"question": "RAG", "scope": {"video_ids": ["dQw4w9WgXcQ"]}}
    response = await env.client.post("/api/chat", json=body)
    job = env.raw_repo.claim(response.json()["job_id"])
    env.raw_repo.fail(
        job["job_id"],
        job["lease_token"],
        AppError("quota_wait", "Fixture waiting", 429, True),
        deadline_exhausted=True,
    )
    monkeypatch.setattr(job_resume, "quota_status", lambda repo: {"status": "waiting", "pools": []})

    async def limited(*args, **kwargs):
        raise AppError("quota_wait", "Fixture waiting", 429, True)

    monkeypatch.setattr(env.answers, "_answer_provider", limited)
    env.settings.adapter_factory = "youtube_answers.team:create_adapters"
    resumed = await env.client.post("/api/jobs/" + job["job_id"] + "/resume", json={})
    assert resumed.status_code == 202, resumed.text
    await env.worker.run_once(resumed.json()["job_id"])
    assert env.repo.get_job(resumed.json()["job_id"])["state"] == "completed"
    replay = await env.client.post("/api/jobs/" + job["job_id"] + "/resume", json={})
    assert replay.json()["job_id"] == resumed.json()["job_id"]
