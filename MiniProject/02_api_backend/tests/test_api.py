import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import VIDEO_A, VIDEO_B, chat_body

from youtube_backend.errors import AppError
from youtube_backend.main import create_app
from youtube_backend.urls import normalize_url


@pytest.mark.parametrize(
    "url",
    [
        f"https://youtu.be/{VIDEO_A}?t=12",
        f"https://www.youtube.com/watch?v={VIDEO_A}&t=10",
        f"https://m.youtube.com/watch?v={VIDEO_A}",
    ],
)
def test_url_normalization(url):
    assert normalize_url(url) == VIDEO_A


@pytest.mark.parametrize(
    "url",
    [
        "http://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
        "https://youtube.com@evil.example/watch?v=dQw4w9WgXcQ",
        "file:///etc/passwd",
        "https://youtu.be:444/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ/other",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=jNQXAC9IVRw",
        "https://youtu.be/short",
    ],
)
def test_url_rejection(url):
    with pytest.raises(AppError):
        normalize_url(url)


def test_health_openapi_errors_and_cors(env):
    assert env.client.get("/health").json()["mode"] == "fixture"
    spec = env.client.get("/openapi.json").json()
    assert {"/api/videos/import", "/api/chat", "/api/research", "/api/jobs/{job_id}"} <= set(
        spec["paths"]
    )
    assert "ChatResponse" in spec["components"]["schemas"]
    response = env.client.post("/api/chat", json={"question": ""})
    assert response.status_code == 422
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert env.client.get("/absent").json()["error"]["code"] == "http_error"
    response = env.client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,Idempotency-Key",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    response = env.client.options(
        "/api/chat",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_batch_import_reports_each_input_and_duplicates(env):
    response = env.client.post(
        "/api/videos/import",
        json={
            "urls": [
                f"https://youtu.be/{VIDEO_A}",
                "https://evil.example/video",
                f"https://www.youtube.com/watch?v={VIDEO_A}",
            ]
        },
    )
    assert response.status_code == 202
    items = response.json()["jobs"]
    assert [i["outcome"] for i in items] == ["accepted", "rejected", "existing"]
    assert items[0]["job_id"] == items[2]["job_id"]
    assert env.client.get("/api/videos").json()["total"] == 1
    assert env.client.get(f"/api/jobs/{items[0]['job_id']}").json()["state"] == "queued"


def test_concurrent_import_is_atomic(env):
    def import_video(_):
        return env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]["job_id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(import_video, range(12)))
    assert len(set(ids)) == 1
    assert env.repo.list_videos(50, 0)["total"] == 1


def test_limits_validation_and_unready_scope(env):
    env.settings.import_max_urls = 1
    response = env.client.post("/api/videos/import", json={"urls": ["x", "y"]})
    assert response.status_code == 422
    env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])
    assert (
        env.client.post("/api/chat", json=chat_body()).json()["error"]["code"] == "video_not_ready"
    )
    assert env.client.get("/api/videos?limit=0").status_code == 422
    assert (
        env.client.get("/api/videos?playlist_id=x").json()["error"]["code"] == "unsupported_filter"
    )
    assert env.client.get("/api/jobs/unknown").status_code == 404
    assert env.client.get("/api/videos/unknown/transcript").status_code == 404


def test_video_library_transcript_and_filters(ready):
    client = ready.client
    result = client.get("/api/videos?limit=1&offset=1&channel_id=fixture-channel").json()
    assert len(result["items"]) == 1 and result["total"] == 2
    assert result["items"][0]["status"] == "ready"
    assert client.get("/api/videos?date_from=2026-02-01").json()["total"] == 0
    assert client.get("/api/videos?date_from=2026-02-01&date_to=2026-01-01").status_code == 422
    result = client.get(f"/api/videos/{VIDEO_A}/transcript?limit=1&offset=1").json()
    assert result["total"] == 3 and result["segments"][0]["start_seconds"] == 12
    assert result["source"] == "fixture"


def test_chat_history_citations_idempotency_and_followup(ready):
    client = ready.client
    body = chat_body()
    response = client.post("/api/chat", json=body, headers={"Idempotency-Key": "turn-one"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "fixture" and data["status"] == "answered"
    assert data["provider_metadata"]["provider"] == "fixture"
    assert data["citations"][1]["url"] == f"https://www.youtube.com/watch?v={VIDEO_A}&t=12s"
    assert all(c["video_id"] == VIDEO_A for c in data["citations"])
    replay = client.post("/api/chat", json=body, headers={"Idempotency-Key": "turn-one"})
    assert replay.json() == data
    assert (
        client.post(
            "/api/chat",
            json=chat_body(question="different"),
            headers={"Idempotency-Key": "turn-one"},
        ).status_code
        == 409
    )
    history = client.get(f"/api/conversations/{data['conversation_id']}").json()
    assert history["total"] == 2
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][1]["citations"][0]["source_available"]
    response = client.post("/api/chat", json=chat_body(conversation_id=data["conversation_id"]))
    assert response.status_code == 200
    assert (
        client.get(f"/api/conversations/{data['conversation_id']}?limit=1&offset=2").json()["total"]
        == 4
    )


def test_unsupported_questions_and_scope_validation(ready):
    client = ready.client
    data = client.post("/api/chat", json=chat_body(question="weather tomorrow")).json()
    assert data["status"] == "insufficient_evidence" and not data["citations"]
    for scope, code in [
        ({"video_ids": []}, "validation_error"),
        ({"video_ids": [VIDEO_A], "playlist_ids": ["p"]}, "unsupported_filter"),
        ({"video_ids": [VIDEO_A], "channel_ids": ["unrelated"]}, "empty_scope"),
        ({"video_ids": [VIDEO_A], "date_from": "2027-01-01"}, "empty_scope"),
        ({"video_ids": ["absent"]}, "video_not_found"),
    ]:
        response = client.post("/api/chat", json={"question": "RAG", "scope": scope})
        assert response.json()["error"]["code"] == code
    assert client.post("/api/chat", json=chat_body(owner_id="someone")).status_code == 422
    assert client.post("/api/chat", json=chat_body(conversation_id="absent")).status_code == 404
    response = client.post(
        "/api/analysis", json={"type": "compare", "scope": {"video_ids": [VIDEO_A]}}
    )
    assert response.json()["error"]["code"] == "comparison_scope"


def test_analysis_research_and_artifact_polling(ready):
    client = ready.client
    scope = {"video_ids": [VIDEO_A, VIDEO_B]}
    paths = [
        ("/api/analysis", {"type": "compare", "scope": scope}),
        ("/api/research", {"goal": "Learn RAG", "scope": scope}),
        ("/api/learning-artifacts", {"type": "quiz", "scope": scope}),
    ]
    jobs = []
    for path, body in paths:
        response = client.post(path, json=body, headers={"Idempotency-Key": "one"})
        assert response.status_code == 202
        assert response.headers["location"].startswith("/api/jobs/")
        job_id = response.json()["job_id"]
        jobs.append(job_id)
        assert (
            client.post(path, json=body, headers={"Idempotency-Key": "one"}).json()["job_id"]
            == job_id
        )
        asyncio.run(ready.worker.run_once(job_id))
        data = client.get(f"/api/jobs/{job_id}").json()
        assert data["state"] == "completed", data
        assert data["result"]["coverage"]["complete"]
        if "artifact_ids" in data["result"]:
            artifact_id = data["result"]["artifact_ids"][0]
            artifact = client.get(f"/api/learning-artifacts/{artifact_id}").json()
            assert artifact["sources_available"] and artifact["mode"] == "fixture"
    run = client.get(f"/api/research/{jobs[1]}").json()
    assert run["run_id"] == jobs[1] and len(run["events"]) == 1
    assert (
        client.get(f"/api/research/{jobs[1]}?after_event_id={run['events'][0]['event_id']}").json()[
            "events"
        ]
        == []
    )
    assert client.get(f"/api/research/{jobs[0]}").status_code == 404
    assert client.post(f"/api/research/{jobs[0]}/cancel").status_code == 404
    assert client.get("/api/learning-artifacts/absent").status_code == 404


def test_unavailable_adapter_is_explicit_and_never_falls_back(env):
    env.settings.adapter_mode = "unavailable"
    app = create_app(env.settings, env.db)
    job = env.repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
    asyncio.run(app.state.worker.run_once(job["job_id"]))
    result = env.repo.get_job(job["job_id"])
    assert result["error_code"] == "dependency_unavailable"
    assert result["state"] == "queued"
    assert env.repo.list_videos(50, 0)["items"][0]["status"] != "ready"
