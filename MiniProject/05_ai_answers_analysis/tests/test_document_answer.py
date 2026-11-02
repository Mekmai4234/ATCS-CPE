from pathlib import Path

import pytest
from google import genai
from test_integration import integrated as integrated
from youtube_backend.document_store import publish
from youtube_backend.quota import QuotaBroker
from youtube_ingestion.documents import load


async def seed(env):
    documents = load(Path(__file__).resolve().parents[2] / "Transcript")
    for document in documents:
        response = await env.client.post(
            "/api/videos/import", json={"urls": [f"https://youtu.be/{document.video_id}"]}
        )
        await env.worker.run_once(response.json()["jobs"][0]["job_id"])
        publish(env.db, document.model_dump())


async def ask(env, question, videos, **extra):
    response = await env.client.post(
        "/api/chat", json={"question": question, "scope": {"video_ids": videos}, **extra}
    )
    assert response.status_code == 202, response.text
    await env.worker.run_once(response.json()["job_id"])
    job = env.repo.get_job(response.json()["job_id"])
    assert job["state"] == "completed", (question, job.get("error_code"), job.get("error_message"))
    return job["result"]


async def test_five_real_documents_local_http_worker_never_dispatches_provider(
    integrated, monkeypatch
):
    env = integrated
    await seed(env)

    def forbidden(*args, **kwargs):
        pytest.fail("Transcript-first path attempted provider/client admission")

    monkeypatch.setattr(env.answers, "_answer_provider", forbidden)
    monkeypatch.setattr(QuotaBroker, "call", forbidden)
    monkeypatch.setattr(genai, "Client", forbidden)
    cases = [
        ("เพลงนี้ชื่ออะไร", ["C0DXctGPWxw"], "รอ SIS (TER)", "document_metadata"),
        ("ใครร้อง", ["C0DXctGPWxw"], "DICEBLUE", "document_metadata"),
        ("เพลงนี้ชื่อว่าอะไร", ["B-zaXo-skGo"], "ดีใจที่ตรงนั้นไม่ใช่เรา", "document_metadata"),
        ("ศิลปินคือใคร", ["B-zaXo-skGo"], "Only Monday", "document_metadata"),
        ("เจ้าของคลิปคือใคร", ["NZImGB4O-X4"], "กายหงิด", "document_metadata"),
        ("ร้านอะไร", ["NZImGB4O-X4"], "เกลือ TCG", "document_metadata"),
        ("ช่องอะไร", ["cWVse_LuFO0"], "Little Moment", "document_metadata"),
        ("ชื่อช่องอะไร", ["f0SQzjp3QzM"], "Prompt Expert", "document_metadata"),
        ("คำว่า good night อยู่ตรงไหน", ["C0DXctGPWxw"], "good night", "document_transcript"),
        ("คลิปพูดอะไรช่วง 02:19–02:29", ["C0DXctGPWxw"], "good night", "document_transcript"),
        ("คำว่า 63,000 อยู่ตรงไหน", ["NZImGB4O-X4"], "63,000", "document_transcript"),
        (
            "retrieval augmented generation",
            ["f0SQzjp3QzM"],
            "retrieval augmented generation",
            "document_transcript",
        ),
        ("ฉันดีใจ ที่ตรงนั้นมันไม่ใช่เรา", ["B-zaXo-skGo"], "ฉันดีใจ", "document_transcript"),
        ("ใครร้อง", ["C0DXctGPWxw", "B-zaXo-skGo"], "Only Monday", "document_metadata"),
    ]
    for question, videos, expected, kind in cases:
        result = await ask(env, question, videos)
        assert expected in result["answer"], (question, result)
        assert result["status"] == "answered"
        assert result["provider_metadata"]["provider"] == "local-document"
        assert all(c["kind"] == kind and c["video_id"] in videos for c in result["citations"])
        if kind == "document_metadata":
            assert all(
                c["start_seconds"] is None and "&t=" not in c["url"] for c in result["citations"]
            )
        if "63,000" in question:
            assert result["citations"][0]["end_seconds"] is None
    for question in (
        "สีเสื้อใน MV",
        "ช่วยยกตัวอย่างให้เข้าใจง่าย",
        "สูตรขนมครก",
        "กำไรสุทธิเท่าไร",
        "คำว่า “ศิลปิน” อยู่ตรงไหน",
        "ใครร้องช่วง 00:19–00:26",
    ):
        result = await ask(env, question, ["C0DXctGPWxw"])
        assert result["status"] == "insufficient_evidence" and not result["citations"]
    assert not env.model.payloads


async def test_opted_in_ai_uses_same_document_evidence_instead_of_old_captions(integrated):
    env = integrated
    await seed(env)
    result = await ask(env, "ช่วยอธิบาย Retrieval", ["cWVse_LuFO0"], response_mode="ai")
    assert result["provider_metadata"]["provider"] == "fixture"
    assert result["citations"] and all(
        c["kind"] == "document_transcript" for c in result["citations"]
    )
    assert env.model.payloads


async def test_ai_failure_falls_back_to_the_same_document_without_zero_call_claim(
    integrated, monkeypatch
):
    from youtube_backend.errors import AppError

    env = integrated
    await seed(env)

    async def unavailable(*args, **kwargs):
        raise AppError("provider_unavailable", "Fixture after admission", 503, True)

    monkeypatch.setattr(env.answers, "_answer_provider", unavailable)
    result = await ask(env, "ใครร้อง", ["C0DXctGPWxw"], response_mode="ai")
    assert "DICEBLUE" in result["answer"]
    assert result["provider_metadata"]["provider"] == "document-fallback"
    assert all(c["kind"] == "document_metadata" for c in result["citations"])
    assert not any("provider calls 0" in note for note in result["coverage"]["notes"])
