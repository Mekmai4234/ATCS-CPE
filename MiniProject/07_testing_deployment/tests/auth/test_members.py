"""Real backend routes and database; external identity/caption/model calls are fixtures."""

import asyncio
import time

import pytest

VIDEO = "dQw4w9WgXcQ"
SCOPE = {"video_ids": [VIDEO]}


def test_login_csrf_and_forged_credentials_are_single_use(identities):
    from fastapi.testclient import TestClient

    with TestClient(identities.app) as client:
        data = client.get("/api/auth/challenge").json()
        body = dict(credential="forged", csrf_token="x" * 43)
        headers = {"Origin": "http://localhost:3000"}
        assert client.post("/api/auth/google", json=body, headers=headers).status_code == 403
        data = client.get("/api/auth/challenge").json()
        body["csrf_token"] = data["csrf_token"]

        def reject(*args):
            raise ValueError("SENTINEL_PRIVATE_CREDENTIAL")

        identities.app.state.auth.verifier = reject
        response = client.post("/api/auth/google", json=body, headers=headers)
        assert response.status_code == 401
        assert "SENTINEL_PRIVATE_CREDENTIAL" not in response.text
        assert client.post("/api/auth/google", json=body, headers=headers).status_code == 403


def test_shared_pending_import_detach_preserves_other_member(identities):
    env = identities
    jobs = []
    for client in (env.a, env.b):
        response = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
        assert response.status_code == 202
        jobs.append(response.json()["jobs"][0]["job_id"])
    assert jobs[0] != jobs[1]
    assert env.a.post(f"/api/jobs/{jobs[0]}/cancel").status_code == 409
    assert env.a.delete(f"/api/videos/{VIDEO}").status_code == 202
    for job in jobs:
        asyncio.run(env.worker.run_once(job))
    assert env.b.get(f"/api/jobs/{jobs[1]}").json()["stage"] == "ready"
    assert env.b.get(f"/api/videos/{VIDEO}/transcript").status_code == 200
    assert env.a.get(f"/api/videos/{VIDEO}/transcript").status_code == 404


def import_video(env, client):
    response = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
    assert response.status_code == 202, response.text
    job = response.json()["jobs"][0]["job_id"]
    asyncio.run(env.worker.run_once(job))
    assert client.get(f"/api/jobs/{job}").json()["stage"] == "ready"
    return job


@pytest.mark.parametrize(
    "claims", [{"aud": "wrong"}, {"iss": "https://evil.invalid"}, {"nonce": "wrong"}, {"exp": 1}]
)
def test_invalid_claims(identities, claims):
    identities.login("invalid", claims=claims, expect=401)


def test_role_injection_and_suspended_login(identities):
    identities.login("escalation", extra={"role": "admin"}, expect=422)
    identities.login("suspended", expect=403)
    assert identities.suspended.get("/api/auth/me").status_code == 401
    assert identities.a.get("/api/admin/users").status_code == 403
    admin_id = identities.users["admin"]["user_id"]
    assert (
        identities.admin.post(f"/api/admin/users/{admin_id}", json={"role": "user"}).status_code
        == 409
    )


def test_rotation_csrf_logout_and_expired_session(identities):
    env = identities
    cookie = env.a.cookies.get("yk_session")
    env.login("a", client=env.a)
    assert env.a.cookies.get("yk_session") != cookie
    assert env.a.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert (
        env.a.post("/api/auth/logout", headers={"Origin": "https://evil.invalid"}).status_code
        == 403
    )
    assert env.a.post("/api/auth/logout").status_code == 200
    assert env.a.get("/api/videos").status_code == 401
    from youtube_backend import database as db

    with env.db.write() as connection:
        connection.execute(db.sessions.update().values(expires_at=int(time.time()) - 1))
    assert env.b.get("/api/auth/me").status_code == 401


def test_private_ids_filters_events_and_shared_detach(identities):
    env = identities
    job = import_video(env, env.a)
    for query in ("", "?offset=0&limit=1", "?channel_id=unknown", "?status=ready"):
        response = env.b.get(f"/api/videos{query}")
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0
    for client in (env.b, env.admin):
        for path in (f"/api/jobs/{job}", f"/api/videos/{VIDEO}/transcript?offset=1&limit=1"):
            assert client.get(path).status_code == 404
        for action in ("cancel", "retry"):
            assert client.post(f"/api/jobs/{job}/{action}").status_code == 404
        assert client.delete(f"/api/videos/{VIDEO}").status_code == 404
    conversation = env.a.post("/api/chat", json={"question": "RAG", "scope": SCOPE}).json()
    assert "conversation_id" in conversation, conversation
    assert (
        env.b.get(
            f"/api/conversations/{conversation['conversation_id']}?offset=0&limit=1"
        ).status_code
        == 404
    )
    run = env.a.post("/api/research", json={"goal": "RAG", "scope": SCOPE}).json()["job_id"]
    for cursor in (0, 1, 999999):
        assert env.b.get(f"/api/research/{run}?after_event_id={cursor}&limit=1").status_code == 404
    assert env.b.post(f"/api/research/{run}/cancel").status_code == 404
    artifact_job = env.a.post(
        "/api/learning-artifacts", json={"type": "quiz", "scope": SCOPE}
    ).json()["job_id"]
    asyncio.run(env.worker.run_once(artifact_job))
    result = env.a.get(f"/api/jobs/{artifact_job}").json()
    artifact = result["result"]["artifact_ids"][0]
    assert env.b.get(f"/api/learning-artifacts/{artifact}").status_code == 404
    import_video(env, env.b)
    assert env.a.delete(f"/api/videos/{VIDEO}").status_code == 202
    assert env.a.get(f"/api/videos/{VIDEO}/transcript").status_code == 404
    assert env.b.get(f"/api/videos/{VIDEO}/transcript").status_code == 200
    assert env.a.get("/api/videos").headers["cache-control"] == "no-store"
