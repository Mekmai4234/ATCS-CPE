"""Floating/full-page chat share the real HTTP/session/ownership contract.

Google verification and provider answers are explicitly test doubles. No browser
or real Google login is claimed by these HTTP integration cases.
"""

import asyncio
import json
import logging
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_identity import ORIGIN, VIDEO, login, ready
from test_identity import identity as identity

from youtube_backend import database as db
from youtube_backend.auth import GoogleLogin
from youtube_backend.schemas import (
    Accepted,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ErrorResponse,
    JobResponse,
)


def test_published_examples_match_current_request_and_response_schemas(identity):
    examples = json.loads(
        (Path(__file__).parent / "fixtures/floating_chat.examples.json").read_text(encoding="utf-8")
    )
    GoogleLogin.model_validate(examples["google_login_request"])
    for name in ("chat_request", "chat_pending_request"):
        ChatRequest.model_validate(examples[name])
    for name, model in (
        ("chat_answered", ChatResponse),
        ("chat_no_evidence", ChatResponse),
        ("chat_accepted", Accepted),
        ("job_queued", JobResponse),
        ("history", ConversationResponse),
        ("empty_scope", ErrorResponse),
        ("unauthenticated", ErrorResponse),
    ):
        model.model_validate(examples[name]["body"])
    schema = identity.transport.get("/openapi.json").json()
    responses = schema["paths"]["/api/chat"]["post"]["responses"]
    assert {"200", "202", "401", "403", "409", "422"} <= responses.keys()


@pytest.mark.parametrize("reason", ["anonymous", "expired", "logout", "suspended"])
def test_session_rejection_is_readable_cross_origin_and_never_cached(identity, reason):
    client = TestClient(identity.app)
    if reason != "anonymous":
        client, user = login(identity, "member", client=client)
        if reason == "logout":
            assert client.post("/api/auth/logout").status_code == 200
        else:
            with identity.db.write() as connection:
                if reason == "expired":
                    connection.execute(db.sessions.update().values(expires_at=0))
                else:
                    connection.execute(
                        db.users.update()
                        .where(db.users.c.user_id == user["user_id"])
                        .values(status="suspended")
                    )
    response = client.get("/api/auth/me", headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN
    assert response.headers.get("Access-Control-Allow-Credentials") == "true"
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_csrf_failure_and_preflight_keep_exact_credentialed_cors(identity):
    client, _ = login(identity, "member")
    denied = client.post("/api/chat", json={}, headers={"X-CSRF-Token": "wrong"})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "csrf_invalid"
    assert denied.headers.get("Access-Control-Allow-Origin") == ORIGIN
    assert denied.headers.get("Cache-Control") == "no-store"
    denied = client.get("/api/auth/me", headers={"Origin": "https://untrusted.example"})
    assert "Access-Control-Allow-Origin" not in denied.headers
    preflight = client.options(
        "/api/chat",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key,x-csrf-token",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert preflight.headers["Access-Control-Allow-Credentials"] == "true"


def test_widget_and_page_share_conversation_and_paginated_history(identity):
    widget, _ = login(identity, "member")
    ready(identity, widget)
    page = TestClient(identity.app)
    page.cookies.update(widget.cookies)
    page.headers.update(widget.headers)
    body = {"question": "RAG", "scope": {"video_ids": [VIDEO]}}
    first = widget.post("/api/chat", json=body, headers={"Idempotency-Key": "widget-turn"})
    assert first.status_code == 200, first.text
    data = first.json()
    replay = page.post("/api/chat", json=body, headers={"Idempotency-Key": "widget-turn"})
    assert replay.json() == data
    body.update(conversation_id=data["conversation_id"], question="RAG follow-up")
    second = page.post("/api/chat", json=body, headers={"Idempotency-Key": "page-turn"})
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == data["conversation_id"]
    path = f"/api/conversations/{data['conversation_id']}"
    first_page = widget.get(path + "?limit=2&offset=0").json()
    next_page = page.get(path + "?limit=2&offset=2").json()
    assert first_page["total"] == next_page["total"] == 4
    assert [m["role"] for m in first_page["messages"] + next_page["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert first_page == page.get(path + "?limit=2&offset=0").json()
    foreign, _ = login(identity, "other")
    assert foreign.get(path).status_code == 404
    assert foreign.get(f"/api/jobs/{data['job_id']}").status_code == 404
    # Sharing the physical video never grants access to the original private chat.
    ready(identity, foreign)
    assert foreign.get(path).status_code == 404
    assert foreign.post("/api/chat", json=body).status_code == 404
    assert widget.delete(f"/api/videos/{VIDEO}").status_code == 202
    history = widget.get(path).json()
    assert all(not c["source_available"] for m in history["messages"] for c in m["citations"])
    assert not widget.get(f"/api/jobs/{data['job_id']}").json()["sources_available"]


def test_accepted_chat_duplicate_busy_and_polling_use_existing_job(identity, monkeypatch):
    client, _ = login(identity, "member")
    ready(identity, client)
    run = identity.worker.run_once

    async def another_worker_holds_turn(job_id):
        return False

    monkeypatch.setattr(identity.worker, "run_once", another_worker_holds_turn)
    body = {"question": "RAG", "scope": {"video_ids": [VIDEO]}}
    headers = {"Idempotency-Key": "pending-turn"}
    accepted = client.post("/api/chat", json=body, headers=headers)
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    assert accepted.headers["Location"] == f"/api/jobs/{job_id}"
    assert client.post("/api/chat", json=body, headers=headers).json() == accepted.json()
    job = client.get(f"/api/jobs/{job_id}").json()
    busy = client.post("/api/chat", json=dict(body, conversation_id=job["conversation_id"]))
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "conversation_busy"
    conflict = client.post("/api/chat", json=dict(body, question="Different"), headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    asyncio.run(run(job_id))
    completed = client.get(f"/api/jobs/{job_id}").json()
    assert completed["state"] == "completed" and completed["result"]["status"] == "answered"
    with identity.db.read() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(db.jobs).where(db.jobs.c.kind == "chat")
            )
            == 1
        )


def test_changed_scope_does_not_send_unselected_history_to_provider(identity, monkeypatch):
    client, _ = login(identity, "member")
    ready(identity, client)
    first = client.post("/api/chat", json={"question": "RAG", "scope": {"video_ids": [VIDEO]}})
    assert first.status_code == 200
    other_video = "jNQXAC9IVRw"
    imported = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{other_video}"]})
    asyncio.run(identity.worker.run_once(imported.json()["jobs"][0]["job_id"]))
    adapter = identity.app.state.adapters.adapter
    original, seen = adapter.answer, []

    async def record(request, sources, history, context):
        seen.extend(history)
        return await original(request, sources, history, context)

    monkeypatch.setattr(adapter, "answer", record)
    response = client.post(
        "/api/chat",
        json={
            "question": "RAG",
            "scope": {"video_ids": [other_video]},
            "conversation_id": first.json()["conversation_id"],
        },
    )
    assert response.status_code == 200, response.text
    assert not seen
    assert all(c["video_id"] == other_video for c in response.json()["citations"])


def test_empty_unready_no_evidence_and_removed_scope_are_distinct(identity, caplog):
    client, _ = login(identity, "member")
    body = {"question": "private-question-marker", "scope": {"video_ids": []}}
    assert client.post("/api/chat", json=body).status_code == 422
    client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
    body["scope"]["video_ids"] = [VIDEO]
    assert client.post("/api/chat", json=body).json()["error"]["code"] == "video_not_ready"
    ready(identity, client)
    with caplog.at_level(logging.INFO, logger="youtube_backend.main"):
        answer = client.post("/api/chat", json=body)
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "insufficient_evidence"
    assert answer.json()["citations"] == []
    assert "private-question-marker" not in caplog.text
    assert "test-credential" not in caplog.text
    assert client.cookies.get("yk_session") not in caplog.text
    client.delete(f"/api/videos/{VIDEO}")
    removed = client.post("/api/chat", json=body)
    assert removed.status_code == 404
    assert removed.json()["error"]["code"] == "video_not_found"
