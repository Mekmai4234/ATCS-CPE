from fastapi.testclient import TestClient
from test_identity import VIDEO, login, ready
from test_identity import identity as identity


def test_conversation_list_is_private_searchable_and_paginated(identity):
    a, _ = login(identity, "history-a")
    ready(identity, a)
    ids = []
    for question in ["ทำความเข้าใจ RAG", "สูตรอาหาร 100%", "คำถามสุดท้าย"]:
        response = a.post("/api/chat", json={"question": question, "scope": {"video_ids": [VIDEO]}})
        assert response.status_code == 200
        ids.append(response.json()["conversation_id"])
    page = a.get("/api/conversations?limit=2").json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["items"][0]["conversation_id"] == ids[-1]
    assert page["items"][0]["title"] == "คำถามสุดท้าย"
    assert page["items"][0]["message_count"] == 2
    assert page["items"][0]["video_ids"] == [VIDEO]
    assert (
        a.get("/api/conversations?limit=2&offset=2").json()["items"][0]["conversation_id"] == ids[0]
    )
    found = a.get("/api/conversations", params={"q": "100%"})
    assert found.json()["total"] == 1  # SQL LIKE wildcards are literal user input.
    assert a.get("/api/conversations?q=missing").json()["total"] == 0
    assert found.headers["Cache-Control"] == "no-store"
    b, _ = login(identity, "history-b", client=TestClient(identity.app))
    ready(identity, b)
    assert b.get("/api/conversations").json()["items"] == []
    assert b.get(f"/api/conversations/{ids[0]}").status_code == 404
    assert identity.transport.get("/api/conversations").status_code == 401
    assert a.get("/api/conversations?limit=0").status_code == 422
    assert a.get("/api/conversations?offset=-1").status_code == 422
    assert a.get("/api/conversations", params={"q": "a" * 201}).status_code == 422


def test_list_keeps_pending_questions_and_original_title(identity, monkeypatch):
    client, _ = login(identity, "history-pending")
    ready(identity, client)

    async def held(job_id):
        return False

    monkeypatch.setattr(identity.worker, "run_once", held)
    response = client.post(
        "/api/chat", json={"question": "คำถามที่ยังรอคำตอบ", "scope": {"video_ids": [VIDEO]}}
    )
    assert response.status_code == 202
    records = client.get("/api/conversations").json()["items"]
    assert records[0]["title"] == "คำถามที่ยังรอคำตอบ"
    assert records[0]["message_count"] == 1
    assert (
        client.get(f"/api/conversations/{records[0]['conversation_id']}").json()["messages"][0][
            "state"
        ]
        == "queued"
    )
