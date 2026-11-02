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
