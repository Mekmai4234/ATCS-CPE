import asyncio
from types import SimpleNamespace

from test_free_tier import budget
from test_identity import identity

__all__ = ["budget", "identity"]
from youtube_backend.config import Settings
from youtube_backend.quota import ProviderReply
from youtube_backend.repository import digest
from youtube_backend.schemas import Citation, Source
from youtube_backend.video_evidence import VideoEvidenceStore, verify_video_citation
from youtube_backend.worker import Worker
from youtube_backend.workspace import worker_status


def test_regenerated_cache_keeps_original_citations_and_full_observations(budget):
    env = budget
    source = Source.model_validate(
        env.repo.get_job(env.context.job_id, internal=True)["payload"]["sources"][0]
    )
    store = VideoEvidenceStore(env.context)
    first = dict(
        id="o1",
        kind="visual",
        text="A" * 160 + " This is a replay, not a new opening.",
        start_seconds=1,
        end_seconds=2,
    )
    citations = []
    for i, obs in enumerate([first, dict(first, text="Different regenerated observation")]):
        permit = env.broker.reserve(
            env.context,
            model=env.settings.llm_model,
            endpoint="generateContent",
            input_tokens=100,
            call_key=f"audit-{i}",
            role="vision",
            input_hash="a" * 64,
        )
        env.broker.dispatch(env.context, permit)
        env.broker.settle(permit, reply=ProviderReply(None, 100, env.settings.llm_model))
        key = store.publish(
            source,
            env.settings.llm_model,
            "same question",
            dict(observations=[obs]),
            permit,
            "a" * 64,
        )
        citations.append(
            Citation(
                citation_id="1",
                chunk_id=digest(obs),
                video_id=source.video_id,
                title=obs["text"][:160],
                start_seconds=1,
                end_seconds=2,
                kind="video",
                observation_cache_id=key,
            )
        )
        with env.repo.db.read() as c:
            job = env.repo._owned(c, env.context.job_id, env.context.lease_token)
            verify_video_citation(env.repo, c, job, citations[-1])
    assert citations[0].observation_cache_id != citations[1].observation_cache_id
    assert (
        store.load(source, env.settings.llm_model, "same question")[0]
        == citations[1].observation_cache_id
    )
    assert "replay" in store.resolve([citations[0]])[0]["text"]
    with env.repo.db.read() as c:
        job = env.repo._owned(c, env.context.job_id, env.context.lease_token)
        verify_video_citation(env.repo, c, job, citations[0])


def test_inline_api_worker_cannot_report_background_worker_ready(tmp_path):
    settings = Settings(
        _env_file=None, database_url=f"sqlite:///{(tmp_path / 'audit.db').as_posix()}"
    )
    assert worker_status(settings)["ready"] is False
    # No background worker is started. This is the same Worker used by the API.
    worker = Worker(SimpleNamespace(claim=lambda _: None), None, settings, report_liveness=False)
    assert asyncio.run(worker.run_once("absent-job")) is False
    assert worker_status(settings)["ready"] is False
    daemon = Worker(SimpleNamespace(claim=lambda _: None), None, settings)
    asyncio.run(daemon.run_once("absent-job"))
    assert worker_status(settings)["ready"] is True


def test_successful_inline_chat_does_not_claim_daemon_readiness(identity):
    from test_identity import VIDEO, login, ready

    client, _ = login(identity, "inline-check")
    ready(identity, client)
    assert client.get("/ready").status_code == 503
    response = client.post(
        "/api/chat", json={"question": "What is RAG?", "scope": {"video_ids": [VIDEO]}}
    )
    assert response.status_code == 200, response.text
    assert client.get("/ready").status_code == 503
