import pytest
from conftest import VIDEO_A
from google import genai
from test_integration import integrated as integrated
from youtube_backend.document_store import publish

from youtube_agent.config import AgentSettings
from youtube_agent.gemini import GeminiModel


async def test_document_learning_and_research_share_frozen_start_only_evidence(integrated):
    env = integrated
    receipt = publish(
        env.db,
        dict(
            document_id="learning-file",
            video_id=VIDEO_A,
            sha256="a" * 64,
            language="th",
            relative_path="learning.txt",
            metadata={},
            timing_status="user_supplied_unverified",
            segments=[
                dict(
                    segment_id="file:1",
                    line=1,
                    text="FILE_EVIDENCE: retrieval finds company documents before generation",
                    start_seconds=19,
                    end_seconds=None,
                    end_method="unknown",
                )
            ],
        ),
    )
    for kind in ("quiz", "flashcards", "study_plan"):
        response = await env.client.post(
            "/api/learning-artifacts",
            json={"type": kind, "topic": "retrieval", "scope": {"video_ids": [VIDEO_A]}, "days": 3},
        )
        assert response.status_code == 202, response.text
        await env.worker.run_once(response.json()["job_id"])
        job = env.repo.get_job(response.json()["job_id"])
        assert job["state"] == "completed", job.get("error_code")
        artifact = (
            await env.client.get("/api/learning-artifacts/" + job["result"]["artifact_ids"][0])
        ).json()
        assert artifact["citations"]
        assert all(
            c["document_version"] == receipt["version"]
            and c["end_seconds"] is None
            and c["kind"] == "document_transcript"
            for c in artifact["citations"]
        )
    response = await env.client.post(
        "/api/research",
        json={"goal": "Learn retrieval", "scope": {"video_ids": [VIDEO_A]}, "days": 3},
    )
    await env.worker.run_once(response.json()["job_id"])
    job = env.repo.get_job(response.json()["job_id"])
    assert job["state"] == "completed", job.get("error_code")
    assert job["result"]["citations"][0]["document_version"] == receipt["version"]


async def test_agent_client_is_not_constructed_for_file_only_startup(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("File-only startup constructed a cloud client")

    monkeypatch.setattr(genai, "Client", forbidden)
    model = GeminiModel(AgentSettings(_env_file=None, gemini_api_key=""))
    await model.close()


def long_document(video, count=400):
    # About 120 KB of passages: beyond the 72 KB learning byte guard.
    return dict(
        document_id="long-file",
        video_id=video,
        sha256="b" * 64,
        language="th",
        relative_path="long.txt",
        metadata={},
        timing_status="user_supplied_unverified",
        segments=[
            dict(
                segment_id=f"long:{i}",
                line=i + 1,
                text=f"ช่วงที่ {i} RAG ค้นเอกสารบริษัทก่อนสร้างคำตอบ " + "รายละเอียด " * 20,
                start_seconds=i * 3,
                end_seconds=i * 3 + 3,
                end_method="next_start",
            )
            for i in range(count)
        ],
    )


async def test_untopiced_learning_over_long_document_spreads_evidence(integrated):
    """Regression: no topic + oversized transcript searched a fixed English phrase,
    found nothing in Thai documents and failed every artifact as insufficient_evidence."""
    env = integrated
    publish(env.db, long_document(VIDEO_A))
    response = await env.client.post(
        "/api/learning-artifacts",
        json={"type": "quiz", "scope": {"video_ids": [VIDEO_A]}},
    )
    await env.worker.run_once(response.json()["job_id"])
    job = env.repo.get_job(response.json()["job_id"])
    assert job["state"] == "completed", job.get("error_code")
    run = env.repo.get_job(response.json()["job_id"])["result"]
    artifact = (await env.client.get("/api/learning-artifacts/" + run["artifact_ids"][0])).json()
    assert artifact["citations"]
    assert all(c["kind"] == "document_transcript" for c in artifact["citations"])


def test_spread_order_is_coarse_to_fine_and_complete():
    from youtube_agent.service import spread_order

    order = spread_order(10)
    assert order[:3] == [0, 8, 4] and sorted(order) == list(range(10))
    assert spread_order(0) == [] and spread_order(1) == [0]


async def test_research_with_paraphrased_goal_still_gets_document_evidence(integrated):
    """Exact-phrase document lookup finds nothing for a paraphrased goal; the agent's
    search must still return authorized passages instead of an empty observation."""
    env = integrated
    publish(env.db, long_document(VIDEO_A))
    response = await env.client.post(
        "/api/research",
        json={"goal": "อธิบายประโยชน์ทางธุรกิจ", "scope": {"video_ids": [VIDEO_A]}, "days": 3},
    )
    await env.worker.run_once(response.json()["job_id"])
    job = env.repo.get_job(response.json()["job_id"])
    assert job["state"] in {"completed", "partial"}, job.get("error_code")
    assert job["result"]["citations"]
    assert all(c["kind"] == "document_transcript" for c in job["result"]["citations"])
