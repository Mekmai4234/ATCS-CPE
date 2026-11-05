import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B
from test_integration import integrated as integrated
from youtube_backend import database as db
from youtube_backend.answer_checkpoint import VERSION
from youtube_backend.provider_errors import provider_error


def fail_final_step_once(model):
    """Return 503 on the first comparison call; batch summaries succeed."""
    original = model.generate
    state = {"failed": False}

    async def generate(data, timeout, **kwargs):
        if data["task"] == "compare" and not state["failed"]:
            state["failed"] = True
            model.payloads.append(data)
            raise provider_error(503)
        return await original(data, timeout, **kwargs)

    model.generate = generate


async def start_compare(env):
    response = await env.client.post(
        "/api/analysis",
        json={"type": "compare", "scope": {"video_ids": [VIDEO_A, VIDEO_B]}},
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def tasks(payloads):
    return [p["task"] for p in payloads]


async def test_retry_resumes_finished_batches_instead_of_restarting(integrated):
    env = integrated
    fail_final_step_once(env.model)
    job_id = await start_compare(env)

    await env.worker.run_once(job_id)
    first = env.repo.get_job(job_id)
    assert first["state"] == "queued", first
    assert first["error_code"] == "provider_unavailable"
    batches = tasks(env.model.payloads).count("summarize_batch")
    assert batches >= 2

    with env.db.write() as c:  # Skip the provider backoff instead of sleeping.
        c.execute(db.jobs.update().where(db.jobs.c.job_id == job_id).values(available_at=0))
    before = len(env.model.payloads)
    await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "completed", job
    # Only the failed final step is sent again; every batch summary came from the checkpoint.
    assert tasks(env.model.payloads[before:]) == ["compare"]
    assert job["result"]["coverage"]["complete"]
    assert {c["video_id"] for c in job["result"]["citations"]} == {VIDEO_A, VIDEO_B}

    with env.db.read() as c:
        rows = (
            c.execute(sa.select(db.v2["cache"]).where(db.v2["cache"].c.prompt_version == VERSION))
            .mappings()
            .all()
        )
    assert len(rows) == batches
    assert {r["owner_id"] for r in rows} == {env.owner["user_id"]}


async def test_checkpoints_never_cross_jobs(integrated):
    env = integrated
    first = await start_compare(env)
    await env.worker.run_once(first)
    assert env.repo.get_job(first)["state"] == "completed"

    before = len(env.model.payloads)
    second = await start_compare(env)
    await env.worker.run_once(second)
    assert env.repo.get_job(second)["state"] == "completed"
    # A new job regenerates every batch: checkpoints only serve retries of the same job.
    assert tasks(env.model.payloads[before:]).count("summarize_batch") == tasks(
        env.model.payloads[:before]
    ).count("summarize_batch")
