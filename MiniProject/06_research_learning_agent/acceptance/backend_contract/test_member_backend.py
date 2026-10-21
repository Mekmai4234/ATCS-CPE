"""Run explicitly against 02's member branch; not part of the legacy core environment.

Put that backend's src and tests directories on PYTHONPATH (see MEMBER_AUTHORIZATION.md).
Only Google/provider responses are fixtures; ownership, jobs and API checks use real 02.
"""

import asyncio

import pytest
import sqlalchemy as sa
from conftest import BranchModel, Knowledge, ScriptedModel
from test_identity import identity as backend_identity
from test_identity import login, ready
from youtube_backend import database as db
from youtube_backend.fixture_adapter import FixtureAdapters

from youtube_agent.config import AgentSettings
from youtube_agent.service import AgentService

identity = backend_identity
VIDEO = "dQw4w9WgXcQ"


@pytest.mark.parametrize("change", ["none", "revoke", "suspend", "expire_cookie"])
def test_member_agent_with_real_backend(identity, change):
    env = identity
    a, user = login(env, "a")
    b, _ = login(env, "b")
    ready(env, a)
    scope = {"video_ids": [VIDEO]}
    assert b.post("/api/research", json={"goal": "RAG", "scope": scope}).status_code == 404
    model = BranchModel()
    original = model.decide
    failures = []

    async def decide(*args):
        result = await original(*args)
        with env.db.write() as connection:
            if change == "revoke":
                connection.execute(
                    db.user_videos.delete().where(db.user_videos.c.user_id == user["user_id"])
                )
            elif change == "suspend":
                connection.execute(
                    db.users.update()
                    .where(db.users.c.user_id == user["user_id"])
                    .values(status="suspended")
                )
            elif change == "expire_cookie":
                connection.execute(
                    db.sessions.update()
                    .where(db.sessions.c.user_id == user["user_id"])
                    .values(expires_at=0)
                )
        return result

    model.decide = decide

    async def research(request, sources, context):
        try:
            records = FixtureAdapters(env.repo, env.settings)._chunks(sources)
            service = AgentService(AgentSettings(_env_file=None), model, Knowledge(records))
            return await service.research(request, sources, context)
        except Exception as exc:
            failures.append(repr(exc))
            raise

    env.worker.adapters.research = research
    response = a.post("/api/research", json={"goal": "RAG", "scope": scope})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert b.get(f"/api/research/{job_id}").status_code == 404
    assert b.post(f"/api/research/{job_id}/cancel").status_code == 404
    asyncio.run(env.worker.run_once(job_id))
    with env.db.read() as connection:
        stored = (
            connection.execute(sa.select(db.jobs).where(db.jobs.c.job_id == job_id))
            .mappings()
            .one()
        )
    if change in {"revoke", "suspend"}:
        assert stored["state"] != "completed" and stored["result"] is None
        assert len(model.history) == 1
    else:
        assert stored["state"] == "completed", (stored["error_code"], failures)
        assert b.get(f"/api/research/{job_id}").status_code == 404
        if change == "expire_cookie":
            assert a.get(f"/api/research/{job_id}").status_code == 401
        else:

            async def artifact(request, sources, context):
                records = FixtureAdapters(env.repo, env.settings)._chunks(sources)
                service = AgentService(
                    AgentSettings(_env_file=None), ScriptedModel(), Knowledge(records)
                )
                return await service.artifact(request, sources, context)

            env.worker.adapters.artifact = artifact
            created = a.post("/api/learning-artifacts", json={"type": "quiz", "scope": scope})
            artifact_job = created.json()["job_id"]
            asyncio.run(env.worker.run_once(artifact_job))
            own = a.get(f"/api/jobs/{artifact_job}").json()
            assert own["state"] == "completed", own
            artifact_id = own["result"]["artifact_ids"][0]
            assert a.get(f"/api/learning-artifacts/{artifact_id}").status_code == 200
            assert b.get(f"/api/learning-artifacts/{artifact_id}").status_code == 404
