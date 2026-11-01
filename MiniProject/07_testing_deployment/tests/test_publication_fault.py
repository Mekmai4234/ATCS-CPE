"""Inject disk-write failure into isolated publication, never a live state directory."""

import sqlite3

import pytest
import sqlalchemy as sa
from test_learning_matrix import domain
from youtube_backend import database as db
from youtube_backend.errors import LeaseLost
from youtube_backend.integrations import ExecutionContext
from youtube_backend.schemas import Source


@pytest.mark.parametrize("statement_prefix", ["INSERT INTO messages", "UPDATE jobs"])
async def test_disk_failure_rolls_back_publication_and_recovery_publishes_once(
    tmp_path, statement_prefix
):
    system = domain()
    async with system.system(tmp_path / "state") as (client, worker):
        response = await client.post(
            "/api/videos/import", json={"urls": [f"https://youtu.be/{system.A}"]}
        )
        await worker.run_once(response.json()["jobs"][0]["job_id"])
        job = worker.repo.enqueue("chat", {"question": "RAG", "scope": {"video_ids": [system.A]}})
        claimed = worker.repo.claim(job["job_id"])
        context = ExecutionContext(
            worker.repo,
            job["job_id"],
            claimed["lease_token"],
            claimed["deadline_at"],
            worker.repo.settings,
        )
        sources = [Source.model_validate(s) for s in claimed["payload"]["sources"]]
        answer = await worker.adapters.answer(
            claimed["payload"]["request"], sources, claimed["payload"]["history"], context
        )

        def disk_full(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith(statement_prefix):
                raise sqlite3.OperationalError("database or disk is full (isolated injection)")

        engine = worker.repo.db.engine
        sa.event.listen(engine, "before_cursor_execute", disk_full)
        try:
            with pytest.raises(sqlite3.OperationalError, match="disk is full"):
                worker.repo.finish(
                    job["job_id"], claimed["lease_token"], answer.model_dump(mode="json")
                )
        finally:
            sa.event.remove(engine, "before_cursor_execute", disk_full)
        with worker.repo.db.read() as connection:
            assert (
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(db.messages)
                    .where(
                        db.messages.c.conversation_id == job["conversation_id"],
                        db.messages.c.role == "assistant",
                    )
                )
                == 0
            )
        assert worker.repo.get_job(job["job_id"])["state"] == "running"
        assert worker.repo.get_job(job["job_id"])["result"] is None
        # Restore writes and retry the same fenced publication, without regenerating.
        worker.repo.finish(job["job_id"], claimed["lease_token"], answer.model_dump(mode="json"))
        with pytest.raises(LeaseLost):
            worker.repo.finish(
                job["job_id"], claimed["lease_token"], answer.model_dump(mode="json")
            )
        history = worker.repo.conversation(job["conversation_id"], 100, 0)
        assert sum(item["role"] == "assistant" for item in history["messages"]) == 1
        assert worker.repo.get_job(job["job_id"])["state"] == "completed"
