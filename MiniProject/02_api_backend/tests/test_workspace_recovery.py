import asyncio
import json
import time

from test_identity import ORIGIN, identity, login
from youtube_backend.workspace import beat, heartbeat_path, worker_status


def test_two_tabs_and_single_use(identity):
    client = identity.transport
    first = client.get("/api/auth/challenge").json()
    second = client.get("/api/auth/challenge").json()

    def verify(token, audience):
        return dict(
            sub="tabs-member",
            aud=audience,
            iss="https://accounts.google.com",
            exp=time.time() + 300,
            nonce=first["nonce"] if token == "first" else second["nonce"],
        )

    identity.app.state.auth.verifier = verify
    for name, data in [("first", first), ("second", second)]:
        response = client.post(
            "/api/auth/google",
            headers={"Origin": ORIGIN},
            json={"credential": name, "csrf_token": data["csrf_token"]},
        )
        assert response.status_code == 200, response.text
        replay = client.post(
            "/api/auth/google",
            headers={"Origin": ORIGIN},
            json={"credential": name, "csrf_token": data["csrf_token"]},
        )
        assert replay.status_code == 403


def test_recovery_is_member_scoped(identity):
    a, _ = login(identity, "recovery-a")
    b, _ = login(identity, "recovery-b")
    # An authenticated import produces a real durable job with ownership.
    result = a.post(
        "/api/videos/import",
        headers={"Origin": ORIGIN, "X-CSRF-Token": a.get("/api/auth/me").json()["csrf_token"]},
        json={"urls": ["https://youtu.be/dQw4w9WgXcQ"]},
    )
    assert result.status_code == 202, result.text
    mine = a.get("/api/member/jobs").json()
    assert mine["total"] == 1 and len(mine["items"]) == 1
    assert b.get("/api/member/jobs").json()["items"] == []
    assert identity.transport.get("/api/member/jobs").status_code == 401
    assert "adapter_identity" not in mine["items"][0] and "history" not in mine["items"][0]


def test_worker_readiness_expires(identity):
    assert not worker_status(identity.settings)["ready"]
    beat(identity.settings)
    assert worker_status(identity.settings)["ready"]
    heartbeat_path(identity.settings).write_text(
        json.dumps({"seen_at": time.time() - 10000}), encoding="utf-8"
    )
    assert worker_status(identity.settings) == {"status": "stale", "ready": False}
    assert identity.transport.get("/health").json()["worker"]["ready"] is False


async def test_idle_worker_publishes_heartbeat(identity):
    assert await identity.worker.run_once() is False
    assert worker_status(identity.settings)["ready"]
