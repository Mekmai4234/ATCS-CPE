import pytest
from test_free_tier import budget
from test_identity import identity

__all__ = ["budget", "identity"]
from youtube_backend.errors import AppError
from youtube_backend.quota import ProviderReply
from youtube_backend.repository import digest
from youtube_backend.schemas import Citation, Source
from youtube_backend.video_evidence import VideoEvidenceStore, verify_video_citation


def test_native_observation_requires_real_reconciled_proof_and_exact_citation(budget):
    env = budget
    source = Source.model_validate(
        env.repo.get_job(env.context.job_id, internal=True)["payload"]["sources"][0]
    )
    store = VideoEvidenceStore(env.context)
    observation = dict(id="o1", kind="visual", text="Fixture card", start_seconds=1, end_seconds=2)
    data = dict(observations=[observation])
    with pytest.raises(AppError, match="reconciled"):
        store.publish(source, env.settings.llm_model, "question", data, "fabricated", "a" * 64)
    permit = env.broker.reserve(
        env.context,
        model=env.settings.llm_model,
        endpoint="generateContent",
        input_tokens=100,
        call_key="native-video",
        role="vision",
        input_hash="a" * 64,
    )
    env.broker.dispatch(env.context, permit)
    env.broker.settle(permit, reply=ProviderReply(None, 100, env.settings.llm_model))
    key = store.publish(source, env.settings.llm_model, "question", data, permit, "a" * 64)
    assert store.load(source, env.settings.llm_model, "different")[1] is None
    assert store.load(source, env.settings.llm_model, "question")[1]["observations"] == [
        observation
    ]
    citation = Citation(
        citation_id="1",
        chunk_id=digest(observation),
        video_id=source.video_id,
        title="Video",
        start_seconds=1,
        end_seconds=2,
        kind="video",
        observation_cache_id=key,
    )
    with env.repo.db.read() as c:
        job = env.repo._owned(c, env.context.job_id, env.context.lease_token)
        verify_video_citation(env.repo, c, job, citation)
        with pytest.raises(AppError, match="match stored"):
            verify_video_citation(
                env.repo, c, job, citation.model_copy(update={"start_seconds": 3})
            )
