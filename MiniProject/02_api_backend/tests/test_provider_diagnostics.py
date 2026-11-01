import json

import pytest

from youtube_backend.errors import AppError
from youtube_backend.provider_errors import provider_error


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_all_transient_server_failures_remain_retryable(status):
    failure = provider_error(status)
    assert failure.retryable
    assert failure.failure_origin == "http"
    assert failure.provider_status == status
    assert not provider_error(400).retryable


async def test_worker_keeps_safe_origin_and_replaces_stale_failure_diagnostic(env, monkeypatch):
    async def fail(*args):
        raise provider_error(503, origin="transport")

    monkeypatch.setattr(env.adapters, "ingest", fail)
    job = env.repo.import_urls(["https://youtu.be/dQw4w9WgXcQ"])[0]
    await env.worker.run_once(job["job_id"])
    saved = env.repo.get_job(job["job_id"])
    assert saved["state"] == "queued"
    assert saved["payload"]["provider_failure"] == {
        "origin": "transport",
        "http_status": None,
        "attempt": 1,
    }
    assert "provider_failure" not in json.dumps(env.repo.public_job(saved))
    with env.db.write() as c:
        from youtube_backend import database as db

        c.execute(db.jobs.update().where(db.jobs.c.job_id == job["job_id"]).values(available_at=0))

    async def invalid(*args):
        raise AppError("invalid_model_output", "Safe invalid output", 502)

    monkeypatch.setattr(env.adapters, "ingest", invalid)
    await env.worker.run_once(job["job_id"])
    saved = env.repo.get_job(job["job_id"])
    assert saved["state"] == "failed"
    assert "provider_failure" not in saved["payload"]
