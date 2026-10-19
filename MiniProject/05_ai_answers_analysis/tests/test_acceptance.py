from pathlib import Path

import httpx
import pytest
from conftest import VIDEO_A, VIDEO_B
from pydantic import ValidationError
from youtube_backend.errors import AppError

from youtube_answers.acceptance import AcceptanceCase, AcceptancePlan, AcceptanceRunner


def plan():
    return AcceptancePlan(
        videos=[f"https://youtu.be/{VIDEO_A}", f"https://youtu.be/{VIDEO_B}"],
        expected_model="selected-model",
        cases=[
            AcceptanceCase(
                id="qa",
                category="supported",
                kind="chat",
                request={"question": "What does RAG retrieve?", "scope": {"video_ids": [VIDEO_A]}},
                review_criteria="The cited transcript must support evidence retrieval.",
            ),
            AcceptanceCase(
                id="followup",
                category="followup",
                kind="chat",
                conversation_from="qa",
                request={"question": "Why?", "scope": {"video_ids": [VIDEO_A]}},
                review_criteria="Resolve the prior question; cite current scoped evidence.",
            ),
            AcceptanceCase(
                id="compare",
                category="contradiction",
                kind="analysis",
                request={"type": "compare", "scope": {"video_ids": [VIDEO_A, VIDEO_B]}},
                review_criteria="Human checks differences against both actual clips.",
            ),
        ],
    )


def answer(video=VIDEO_A):
    return {
        "status": "answered",
        "answer": "RAG retrieves evidence. [1]",
        "citations": [
            {
                "citation_id": "1",
                "chunk_id": "chunk-1",
                "video_id": video,
                "title": "Real title",
                "start_seconds": 0,
                "end_seconds": 10,
                "url": f"https://www.youtube.com/watch?v={video}&t=0s",
            }
        ],
        "coverage": {
            "expected_videos": 1,
            "processed_videos": 1,
            "expected_chunks": 2,
            "processed_chunks": 1,
            "complete": False,
            "notes": ["Ranked retrieval only."],
        },
        "provider_metadata": {
            "provider": "gemini",
            "requested_model": "selected-model",
            "returned_model": "actual-returned-model",
            "usage": {"input": 10},
            "latency_ms": 12,
        },
        "conversation_id": "conversation-1",
        "job_id": "chat-1",
    }


def health():
    return {
        "mode": "custom",
        "synthetic_data": False,
        "integration_profile": "live",
        "capabilities": dict.fromkeys(
            ("ingest", "index", "answer", "analyze", "evidence", "inventory"), "available"
        ),
    }


async def test_http_acceptance_polls_follows_history_and_builds_review_packets():
    sent = []

    def handler(request):
        import json

        path = request.url.path
        if path == "/health":
            data = health()
        elif path == "/api/videos/import":
            data = {
                "jobs": [
                    {"outcome": "accepted", "job_id": "import-1"},
                    {"outcome": "existing", "job_id": "import-2"},
                ]
            }
        elif path.startswith("/api/jobs/import-"):
            data = {"state": "completed", "stage": "ready", "result": {"source": {}}}
        elif path == "/api/videos":
            data = {
                "items": [
                    {
                        "video_id": v,
                        "status": "ready",
                        "title": "Real title",
                        "transcript_version": "v1",
                    }
                    for v in (VIDEO_A, VIDEO_B)
                ],
                "total": 2,
            }
        elif path.endswith("/transcript"):
            data = {
                "source": "youtube_captions:manual",
                "transcript_version": "v1",
                "total": 1,
                "segments": [
                    {
                        "segment_id": "s1",
                        "text": "RAG retrieves evidence before answering.",
                        "start_seconds": 0,
                        "duration_seconds": 10,
                    }
                ],
            }
        elif path in {"/api/chat", "/api/analysis"}:
            sent.append(json.loads(request.content))
            data = answer() if path.endswith("chat") else {"job_id": "analysis-1"}
        elif path == "/api/jobs/analysis-1":
            value = answer()
            other = answer(VIDEO_B)["citations"][0]
            other.update(citation_id="2", chunk_id="chunk-2")
            value["citations"].append(other)
            value["answer"] = "Both videos discuss evidence retrieval. [1] [2]"
            value["coverage"].update(
                expected_videos=2, processed_videos=2, processed_chunks=2, complete=True
            )
            data = {"state": "completed", "result": value}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        report = await AcceptanceRunner(client, poll_interval=0).run(plan())
    assert report["structural_checks_passed"]
    assert report["semantic_acceptance"] == "pending_human_review"
    assert sent[1]["conversation_id"] == "conversation-1"
    result = report["results"][0]
    assert result["result"]["provider_metadata"]["usage"] == {"input": 10}
    assert result["wall_latency_ms"] >= 0
    claim = result["claim_reviews"][0]
    assert claim["semantic_support"] == "pending_human_review"
    assert claim["sources"][0]["transcript_segments"][0]["text"].startswith("RAG retrieves")
    assert report["missing_acceptance_categories"]  # No false full acceptance claim.


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "fixture"},
        {"synthetic_data": True},
        {"integration_profile": "offline"},
        {"capabilities": {"answer": "unavailable"}},
    ],
)
async def test_acceptance_rejects_fixture_or_incomplete_runtime_before_import(change):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={**health(), **change})

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as c:
        with pytest.raises(AppError) as caught:
            await AcceptanceRunner(c).run(plan())
    assert caught.value.code == "acceptance_wrong_runtime" and calls == ["/health"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "Wrong title"),
        ("start_seconds", 99),
        ("video_id", VIDEO_B),
        ("url", "https://example.com/fake"),
    ],
)
def test_review_rejects_wrong_title_time_scope_or_url(field, value):
    case = plan().cases[0]
    result = answer()
    result["citations"][0][field] = value
    if field == "start_seconds":
        result["citations"][0]["end_seconds"] = 100
    runner = AcceptanceRunner(None)
    runner.transcripts = {VIDEO_A: [{"start_seconds": 0, "duration_seconds": 10, "text": "RAG"}]}
    videos = {VIDEO_A: {"title": "Real title", "transcript_version": "v1"}}
    report = runner._review(case, result, videos, "selected-model")
    assert not report["structural_checks_passed"]
    assert report["semantic_review"] == "pending_human_review"


def test_unsupported_no_generation_can_be_valid_without_claims():
    case = plan().cases[0]
    case.expected_status = "insufficient_evidence"
    result = answer()
    result.update(status="insufficient_evidence", answer="No evidence.", citations=[])
    result["provider_metadata"]["provider"] = "none"
    result["coverage"].update(processed_videos=0, processed_chunks=0)
    report = AcceptanceRunner(None)._review(case, result, {}, "selected-model")
    assert report["structural_checks_passed"] and not report["claim_reviews"]


def test_plan_rejects_external_scope_and_invalid_followup():
    data = plan().model_dump()
    data["cases"][0]["request"]["scope"]["video_ids"] = ["outside1234"]
    with pytest.raises(ValidationError):
        AcceptancePlan.model_validate(data)
    data = plan().model_dump()
    data["cases"][0]["conversation_from"] = "future-case"
    with pytest.raises(ValidationError):
        AcceptancePlan.model_validate(data)


def test_cli_requires_live_before_opening_plan_or_sending_requests(monkeypatch):
    from youtube_answers.acceptance import main

    monkeypatch.setattr(
        "sys.argv", ["yk-answers-acceptance", "--plan", "missing.json", "--output", "unused.json"]
    )
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 2 and not Path("unused.json").exists()


async def test_failed_jobs_and_poll_deadlines_are_classified():
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"state": "failed", "error_code": "provider-secret"})
        ),
    ) as client:
        with pytest.raises(AppError) as caught:
            await AcceptanceRunner(client)._result({"job_id": "job"})
        assert caught.value.code == "acceptance_job_failed"
        assert "secret" not in str(caught.value)
        with pytest.raises(AppError) as caught:
            await AcceptanceRunner(client, poll_timeout=0)._result({"job_id": "job"})
        assert caught.value.code == "acceptance_poll_timeout"
