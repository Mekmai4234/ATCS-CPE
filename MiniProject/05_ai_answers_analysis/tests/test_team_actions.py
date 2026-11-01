"""Production TeamAdapters delegation through authenticated HTTP and the real worker."""

import sqlalchemy as sa
from test_integration import integrated as integrated
from youtube_backend import database as db


async def test_team_reindex_is_admin_only_idempotent_and_publishes(integrated):
    env = integrated
    from youtube_answers.team import TeamAdapters

    env.worker.adapters = env.app.state.adapters.adapter = TeamAdapters(
        env.answers, env.adapters.ingestion, env.adapters.agent
    )
    env.adapters = env.worker.adapters
    env.settings.trial_reindex_enabled = True
    video = "dQw4w9WgXcQ"
    endpoint = f"/api/videos/{video}/trial-reindex"
    headers = {"Idempotency-Key": "team-trial"}
    denied = await env.client.post(endpoint, headers=headers)
    assert denied.status_code == 403
    with env.db.write() as c:
        c.execute(
            sa.update(db.users)
            .where(db.users.c.user_id == env.owner["user_id"])
            .values(role="admin")
        )
    response = await env.client.post(endpoint, headers=headers)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert (await env.client.post(endpoint, headers=headers)).json()["job_id"] == job_id
    await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "completed", job
    assert job["result"]["complete"] is True
    assert env.adapters.provider_operations["reindex"] == env.answers.provider_operations["reindex"]
    assert env.adapters.fresh_generation == ("artifact", "research")
