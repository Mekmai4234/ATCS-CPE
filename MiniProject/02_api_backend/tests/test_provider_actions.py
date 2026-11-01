import asyncio
import json

import httpx
import sqlalchemy as sa
from test_identity import VIDEO, login, ready
from test_identity import identity as identity

from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.provider_status import provider_status


def test_provider_status_is_authenticated_read_only_and_does_not_leak_configuration(identity):
    env = identity
    assert env.transport.get("/api/providers").status_code == 401
    client, _ = login(env, "a")
    data = client.get("/api/providers").json()
    assert data["selection"] == "server_configuration"
    assert data["model_calls"] == 0 and data["admission_guaranteed"] is False
    assert data["synthetic"] is True
    assert data["regenerate"] == []
    text = json.dumps(data)
    assert "local_base_url" not in text and "gemini_api_key" not in text
    assert client.get("/api/providers").json()["local"]["state"] == "not_selected"


async def test_local_status_observes_digest_without_generating_or_inventing_loading(identity):
    env = identity
    _, user = login(env, "a")
    env.settings.generation_provider = "ollama"
    env.settings.local_model, env.settings.local_model_digest = "test:local", "a" * 64
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"models": [{"name": "test:local", "digest": "a" * 64}]})

    token = actor_id.set(user["user_id"])
    try:
        report = await provider_status(
            env.repo, env.app.state.adapters, transport=httpx.MockTransport(handler)
        )
    finally:
        actor_id.reset(token)
    assert report["local"]["state"] == "ready"
    assert report["loading_observed"] is False
    assert seen == ["/api/tags"]
    assert report["operations"]["answer"]["mounted"] is False
    assert report["synthetic"] is True


def test_explicit_regeneration_is_owned_idempotent_frozen_and_keeps_original_result(identity):
    env = identity
    client, _ = login(env, "a")
    ready(env, client)
    body = {"type": "quiz", "scope": {"video_ids": [VIDEO]}}
    first = client.post("/api/learning-artifacts", json=body).json()["job_id"]
    asyncio.run(env.worker.run_once(first))
    original = client.get("/api/jobs/" + first).json()
    endpoint = f"/api/jobs/{first}/regenerate"
    assert client.post(endpoint, headers={"Idempotency-Key": "fresh"}).status_code == 409
    env.app.state.adapters.adapter.fresh_generation = ("artifact",)
    assert client.post(endpoint).status_code == 422
    response = client.post(endpoint, headers={"Idempotency-Key": "fresh"})
    assert response.status_code == 202, response.text
    new_id = response.json()["job_id"]
    assert new_id != first
    assert client.post(endpoint, headers={"Idempotency-Key": "fresh"}).json()["job_id"] == new_id
    with env.db.read() as c:
        row = c.execute(sa.select(db.jobs).where(db.jobs.c.job_id == new_id)).mappings().one()
    assert row["payload"]["bypass_cache"] is True
    assert row["payload"].get("adapter_checkpoints") is None
    assert row["payload"]["regenerates"] == first
    assert client.get("/api/jobs/" + first).json()["result"] == original["result"]
    assert client.get("/api/jobs/" + first).json()["execution"] == original["execution"]
    other, _ = login(env, "b")
    assert other.post(endpoint, headers={"Idempotency-Key": "fresh"}).status_code == 404
    assert "bypass_cache" not in client.get("/api/jobs/" + new_id).text


def test_trial_reindex_default_off_and_production_forbidden(identity):
    env = identity
    client, _ = login(env, "a")
    env.app.state.adapters.adapter.reindex = lambda *args: None
    endpoint = f"/api/videos/{VIDEO}/trial-reindex"
    assert client.post(endpoint, headers={"Idempotency-Key": "trial"}).status_code == 409
    env.settings.trial_reindex_enabled = True
    env.settings.app_env = "production"
    assert client.post(endpoint, headers={"Idempotency-Key": "trial"}).status_code == 409
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == 0
