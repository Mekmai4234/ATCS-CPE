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
