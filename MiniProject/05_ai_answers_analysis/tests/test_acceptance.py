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
        elif path == "/api/auth/me":
            data = {"user": {"user_id": "member-a", "status": "active"}, "csrf_token": "s" * 64}
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
        report = await AcceptanceRunner(
            client, poll_interval=0, origin="http://localhost:3000"
        ).run(plan())
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


@pytest.mark.parametrize(
    "arguments,request_timeout,poll_timeout",
    [
        ([], 210, 300),
        (["--request-timeout", "95", "--poll-timeout", "140"], 95, 140),
    ],
)
def test_cli_uses_configured_http_and_polling_budgets(
    tmp_path, monkeypatch, arguments, request_timeout, poll_timeout
):
    from youtube_answers import acceptance

    monkeypatch.setenv("YK_ACCEPTANCE_SESSION", "test-only-session")

    plan_file, output = tmp_path / "plan.json", tmp_path / "result.json"
    plan_file.write_text(plan().model_dump_json(), encoding="utf-8")
    client_type = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    def client(**kwargs):
        return client_type(**kwargs, transport=httpx.MockTransport(handler))

    async def run(self, _plan):
        assert self.poll_timeout == poll_timeout
        await self._request("POST", "/api/chat", json={})
        return {"structural_checks_passed": True, "semantic_acceptance": "pending_human_review"}

    monkeypatch.setattr(acceptance.httpx, "AsyncClient", client)
    monkeypatch.setattr(acceptance.AcceptanceRunner, "run", run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "yk-answers-acceptance",
            "--live",
            "--plan",
            str(plan_file),
            "--output",
            str(output),
            *arguments,
        ],
    )
    assert acceptance.main() == 0
    assert requests[0].extensions["timeout"]["read"] == request_timeout
    assert requests[0].extensions["timeout"]["write"] == request_timeout
    assert requests[0].extensions["timeout"]["connect"] == 10
    assert "test-only-session" not in output.read_text("utf-8")


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "invalid"])
def test_cli_rejects_invalid_timeout_before_any_network(value):
    import argparse

    from youtube_answers.acceptance import positive_seconds

    with pytest.raises(argparse.ArgumentTypeError):
        positive_seconds(value)


@pytest.mark.parametrize("timeout,passes", [(0.01, False), (1.0, True)])
async def test_real_http_read_budget_allows_slow_response_within_configured_limit(timeout, passes):
    import asyncio
    from contextlib import suppress

    tasks = set()

    async def respond(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            # The client can time out before sending headers on a loaded Windows
            # host. Do not leave an accepted test socket waiting forever.
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
            await asyncio.sleep(0.1)
            writer.write(
                b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}'
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 1)
            tasks.discard(task)

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=timeout
        ) as client:
            runner = AcceptanceRunner(client)
            if passes:
                assert await runner._request("GET", "/slow-chat") == {"ok": True}
            else:
                with pytest.raises(AppError) as caught:
                    await runner._request("GET", "/slow-chat")
                assert caught.value.code == "acceptance_request_timeout"
    finally:
        server.close()
        await server.wait_closed()
        if tasks:
            pending = list(tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.parametrize(
    "status,code", [(401, "authentication_required"), (403, "permission_denied")]
)
async def test_session_errors_are_not_insufficient_evidence_and_are_redacted(status, code):
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, json={"error": "session-secret csrf-secret"})
        ),
    ) as client:
        with pytest.raises(AppError) as caught:
            await AcceptanceRunner(client)._session()
    assert caught.value.code == code and caught.value.status_code == status
    assert "secret" not in str(caught.value)


async def test_session_csrf_refresh_is_bound_to_one_actor():
    actors = iter(["a", "b"])

    def handler(request):
        return httpx.Response(
            200,
            json={
                "user": {"user_id": next(actors), "status": "active"},
                "csrf_token": "c" * 64,
            },
        )

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as client:
        runner = AcceptanceRunner(client, origin="http://localhost:3000")
        await runner._session()
        assert client.headers["X-CSRF-Token"] == "c" * 64
        assert client.headers["Origin"] == "http://localhost:3000"
        with pytest.raises(AppError) as caught:
            await runner._session()
        assert caught.value.code == "acceptance_actor_changed"


def test_cli_missing_session_fails_closed_without_network_or_secret_report(tmp_path, monkeypatch):
    from youtube_answers import acceptance

    monkeypatch.delenv("YK_ACCEPTANCE_SESSION", raising=False)
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv", ["acceptance", "--live", "--plan", "missing.json", "--output", str(output)]
    )
    monkeypatch.setattr(
        acceptance.httpx, "AsyncClient", lambda **_: pytest.fail("Network not allowed")
    )
    assert acceptance.main() == 1
    assert '"error_code": "acceptance_authentication_required"' in output.read_text("utf-8")
