import time

import httpx
import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, transcript
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.job_actions import trial_reindex
from youtube_backend.local_inference import LocalInference
from youtube_backend.worker import Worker

from youtube_rag.config import RagSettings
from youtube_rag.integration import RagAdapters
from youtube_rag.manifest import active, runs


async def test_authenticated_local_trial_worker_preserves_old_index_and_resumes_batches(
    env, monkeypatch
):
    env.settings.auth_enabled = True
    env.settings.trial_reindex_enabled = True
    with env.db.write() as c:
        c.execute(
            db.users.insert().values(
                user_id="admin",
                google_sub="trial-admin",
                role="admin",
                status="active",
                created_at=time.time(),
                updated_at=time.time(),
            )
        )
    token = actor_id.set("admin")
    adapter = None
    try:
        source = await env.ready()
        with env.db.read() as c:
            previous = c.scalar(sa.select(active.c.run_id))
        config = RagSettings(
            _env_file=None,
            **dict(
                env.config.model_dump(),
                embedding_provider="ollama",
                embedding_model="test:embed",
                local_embedding_model="test:embed",
                local_embedding_digest="a" * 64,
                embedding_batch_size=1,
            ),
        )
        env.settings.embedding_provider = "ollama"
        env.settings.embedding_model = env.settings.local_embedding_model = "test:embed"
        env.settings.local_embedding_digest = "a" * 64
        env.settings.embedding_dimensions = config.embedding_dimensions
        adapter = RagAdapters(settings=env.settings, repository=env.repo, rag_settings=config)
        dispatches = []
        fail = True

        def transport(request):
            nonlocal fail
            if request.url.path == "/api/tags":
                return httpx.Response(
                    200, json={"models": [{"name": "test:embed", "digest": "a" * 64}]}
                )
            dispatches.append(1)
            if len(dispatches) == 2 and fail:
                fail = False
                raise httpx.ReadTimeout("synthetic timeout after send")
            return httpx.Response(
                200,
                json={
                    "model": "test:embed",
                    "embeddings": [[1.0] + [0.0] * (config.embedding_dimensions - 1)],
                },
            )

        async def local_call(context, **request):
            return await LocalInference(context, transport=httpx.MockTransport(transport)).call(
                **request
            )

        monkeypatch.setattr(ExecutionContext, "local_inference", local_call)
        queued = trial_reindex(env.repo, VIDEO_A, "trial-1")
        assert trial_reindex(env.repo, VIDEO_A, "trial-1")["job_id"] == queued["job_id"]
        worker = Worker(env.repo, adapter, env.settings)
        await worker.run_once(queued["job_id"])
        with env.db.read() as c:
            assert c.scalar(sa.select(active.c.run_id)) == previous
            assert c.scalar(sa.select(db.videos.c.status)) == "ready"
        # Expire only this disposable fixture's uncertain local capacity. Never refund sent work.
        with env.db.write() as c:
            c.execute(db.v2["reservations"].update().values(expires_at=0))
            c.execute(
                db.jobs.update().where(db.jobs.c.job_id == queued["job_id"]).values(available_at=0)
            )
        await worker.run_once(queued["job_id"])
        result = env.repo.get_job(queued["job_id"])
        assert result["state"] == "completed", result
        with env.db.read() as c:
            current = c.scalar(sa.select(active.c.run_id))
            assert current != previous
            assert c.scalar(sa.select(runs.c.state).where(runs.c.run_id == previous)) == "retired"
            assert c.scalar(sa.select(db.videos.c.transcript_version)) == source.transcript_version
        # The old physical vectors remain available for paired rollback; no transcript fetch occurs.
        old = await env.rag.vectors.call("get", 30, where={"run_id": previous}, include=[])
        assert old["ids"]
        assert len(dispatches) == result["result"]["chunk_count"] + 1
        with pytest.raises(AppError):
            await adapter.reindex(source, transcript(), env.query(VIDEO_A).ctx)
    finally:
        actor_id.reset(token)
        if adapter is not None:
            await adapter.close()


async def test_bounded_selector_finds_tail_terms_and_cannot_reuse_revoked_scope(env):
    original = transcript()
    from youtube_backend.schemas import Segment

    original.segments = [
        Segment(
            segment_id=f"s{i}",
            text=("คีย์เวิร์ดท้ายคลิป Kubernetes" if i == 73 else f"Fact {i}: basic material."),
            start_seconds=i * 3,
            duration_seconds=3,
        )
        for i in range(74)
    ]
    await env.ready(value=original)
    query = env.query(VIDEO_A)
    selected = await env.rag.select_context(
        "Kubernetes ท้ายคลิป", query.sources, query.execution, limit=12
    )
    assert any("Kubernetes" in chunk.text for chunk in selected["items"])
    assert selected["model_calls"] == 0 and selected["retrieved_chunks"] <= 12
    env.repo.delete_video(VIDEO_A)
    with pytest.raises(AppError):
        await env.rag.select_context("Kubernetes", query.sources, query.execution)
