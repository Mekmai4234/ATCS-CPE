import pytest
from test_integration import integrated as integrated
from youtube_backend.errors import AppError


async def local_chat(env, question, conversation=None, video="dQw4w9WgXcQ"):
    body = {"question": question, "scope": {"video_ids": [video]}}
    if conversation:
        body["conversation_id"] = conversation
    response = await env.client.post("/api/chat", json=body)
    assert response.status_code in {200, 202}, response.text
    await env.worker.run_once(response.json()["job_id"])
    job = env.repo.get_job(response.json()["job_id"])
    assert job["state"] == "completed", job
    return job["result"]


@pytest.fixture
def fallback(integrated, monkeypatch):
    async def limited(*args, **kwargs):
        raise AppError("quota_wait", "Fixture provider unavailable", 429, True)

    monkeypatch.setattr(integrated.answers, "_answer_provider", limited)
    return integrated


@pytest.mark.parametrize("question", ["photosynthesis", "การสังเคราะห์ด้วยแสง"])
async def test_new_topic_does_not_inherit_old_keywords(fallback, question):
    env = fallback
    fresh = await local_chat(env, question)
    first = await local_chat(env, "RAG")
    changed = await local_chat(env, question, first["conversation_id"])
    assert fresh["status"] == changed["status"] == "insufficient_evidence"
    assert not changed["citations"]


async def test_out_of_range_fallback_never_returns_early_clip_citations(fallback):
    result = await local_chat(fallback, "RAG ช่วงเวลา 10:00-10:10 กล่าวถึงอะไร")
    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == []


@pytest.mark.parametrize(
    "followup",
    [
        "Explain more",
        "ขยายความหน่อย",
        "ยกตัวอย่างเรื่องนั้น",
        "ช่วยยกตัวอย่างให้เข้าใจง่าย",
        "ขยายความหน่อยครับ",
        "ช่วยยกตัวอย่างให้เข้าใจง่ายหน่อยค่ะ",
        "ขอช่วยอธิบายเพิ่มเติมหน่อยนะครับ",
    ],
)
async def test_explicit_followup_retains_only_the_current_authorized_topic(fallback, followup):
    first = await local_chat(fallback, "RAG คืออะไร")
    result = await local_chat(fallback, followup, first["conversation_id"])
    assert result["status"] == "answered" and result["citations"]
    assert all(c["video_id"] == "dQw4w9WgXcQ" for c in result["citations"])
    assert result["provider_metadata"]["latency_ms"] > 0
    assert result["provider_metadata"]["usage"]["generate_requests"] == 0
    assert fallback.model.payloads == []
    changed = await local_chat(
        fallback, "ช่วยอธิบาย photosynthesis หน่อยครับ", result["conversation_id"]
    )
    assert changed["status"] == "insufficient_evidence" and not changed["citations"]
    assert fallback.model.payloads == []


@pytest.mark.parametrize("question", ["Explain more", "ขยายความหน่อย", "ในภาพมี RAG อะไรบ้าง"])
async def test_ambiguous_or_visual_fallback_abstains(fallback, question):
    result = await local_chat(fallback, question)
    assert result["status"] == "insufficient_evidence" and not result["citations"]


@pytest.mark.parametrize(
    "clock,keyword,found",
    [
        ("00:00-00:05", "RAG", True),
        ("00:10 to 00:11", "หลักฐาน", True),
        ("๐๐:๑๐ ถึง ๐๐:๑๑", "หลักฐาน", True),
        ("00:00:10–00:00:11", "หลักฐาน", True),
        ("00:20-00:21", "RAG", False),
        ("10:00-10:10", "RAG", False),
    ],
)
async def test_fallback_time_scope_filters_neighbors_and_exposes_crossing_chunks(
    fallback, clock, keyword, found
):
    from conftest import source

    from youtube_answers.question_scope import time_window

    question = f"{keyword} ช่วงเวลา {clock} กล่าวถึงอะไร"
    result = await local_chat(fallback, question)
    assert (result["status"] == "answered") == found
    start, end = time_window(question, source())
    assert all(c["end_seconds"] > start and c["start_seconds"] < end for c in result["citations"])
    assert any("ค้นเฉพาะช่วง" in note for note in result["coverage"]["notes"])
    if found:
        assert any("คร่อมขอบช่วง" in note for note in result["coverage"]["notes"])


async def test_new_clip_cannot_inherit_a_previous_conversations_topic(fallback):
    first = await local_chat(fallback, "RAG")
    result = await local_chat(fallback, "photosynthesis", video="jNQXAC9IVRw")
    assert result["conversation_id"] != first["conversation_id"]
    assert result["status"] == "insufficient_evidence" and not result["citations"]


async def test_provider_recovery_does_not_reuse_the_lexical_fallback(integrated, monkeypatch):
    env = integrated
    with monkeypatch.context() as limited:

        async def unavailable(*args, **kwargs):
            raise AppError("quota_wait", "Fixture down", 429, True)

        limited.setattr(env.answers, "_answer_provider", unavailable)
        first = await local_chat(env, "RAG")
    second = await local_chat(env, "RAG")
    assert first["provider_metadata"]["provider"] == "local-evidence"
    assert second["provider_metadata"]["provider"] == "fixture"
    assert first["assistant_message_id"] != second["assistant_message_id"]
    assert len(env.model.payloads) == 1


@pytest.mark.parametrize(
    "question,code",
    [("RAG 01:99", "invalid_video_time"), ("RAG 00:10-00:00", "invalid_video_time_range")],
)
async def test_invalid_time_is_rejected_before_provider_dispatch(
    integrated, monkeypatch, question, code
):
    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid time must not enter provider admission")

    monkeypatch.setattr(integrated.answers, "_answer_provider", forbidden)
    response = await integrated.client.post(
        "/api/chat", json={"question": question, "scope": {"video_ids": ["dQw4w9WgXcQ"]}}
    )
    await integrated.worker.run_once(response.json()["job_id"])
    job = integrated.repo.get_job(response.json()["job_id"])
    assert job["error_code"] == code and job["result"] is None


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
