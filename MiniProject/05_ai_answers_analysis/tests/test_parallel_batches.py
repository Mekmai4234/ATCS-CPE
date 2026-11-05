import asyncio

import pytest
from conftest import VIDEO_A, VIDEO_B, chunk, metadata, source
from youtube_backend.errors import AppError
from youtube_backend.provider_errors import provider_error

from youtube_answers.models import Generated, GeneratedAnswer, error

COMPARE = {"type": "compare", "scope": {"video_ids": [VIDEO_A, VIDEO_B]}}


def key(data):
    return tuple(c for n in data["untrusted_evidence"] for c in n["citation_ids"])


def long_two_videos(env):
    """Several summarize batches per video under a small context budget."""
    env.sources.append(source(VIDEO_B))
    env.config.max_context_tokens = 6000
    text = "หลักฐาน RAG " * 55
    env.knowledge.chunks = [chunk(i, text=text) for i in range(8)] + [
        chunk(i, VIDEO_B, text=text) for i in range(8)
    ]


class Tracker:
    """Fixture model: later batches finish first; records peak concurrency."""

    def __init__(self, env, fail=None):
        self.env, self.fail = env, fail or {}
        self.order, self.active, self.peak = {}, 0, 0

    async def generate(self, data, timeout):
        self.env.model.payloads.append(data)
        refs = list(dict.fromkeys(key(data)))
        if data["task"] == "summarize_batch":
            index = self.order.setdefault(key(data), len(self.order))
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.05 / (index + 1))  # Earlier batches are slower.
                if index in self.fail:
                    raise self.fail[index]
            finally:
                self.active -= 1
            label = f"batch-{index}"
        else:
            label = data["task"]
        meta = metadata().model_copy(update={"returned_model": f"fixture-{label}"})
        answer = {"status": "answered", "statements": [{"text": label, "citation_ids": refs}]}
        return Generated(GeneratedAnswer.model_validate(answer), meta)


async def run(env, concurrency, fail=None):
    env.model.payloads.clear()
    env.config.answer_batch_concurrency = concurrency
    tracker = Tracker(env, fail)
    env.model.generate = tracker.generate
    return await env.service.analyze(COMPARE, env.sources, env.ctx), tracker


async def test_parallel_batches_match_one_by_one_order(env):
    long_two_videos(env)
    sequential, one = await run(env, 1)
    serial_final = env.model.payloads[-1]
    parallel, many = await run(env, 3)
    parallel_final = env.model.payloads[-1]

    assert len(many.order) > 3, "fixture must need more batches than the concurrency cap"
    assert one.peak == 1 and many.peak == 3
    # Batches finished out of order, yet the synthesis input and the result are identical.
    assert parallel_final == serial_final
    assert [s["text"] for s in parallel_final["untrusted_evidence"]] == [
        f"batch-{i}" for i in range(len(many.order))
    ]
    assert parallel.model_dump(exclude={"provider_metadata": {"latency_ms"}}) == (
        sequential.model_dump(exclude={"provider_metadata": {"latency_ms"}})
    )
    assert parallel.coverage.complete and parallel.coverage.processed_chunks == 16


async def test_failure_stops_queued_batches_and_raises_earliest_error(env):
    long_two_videos(env)
    # Batch 1 fails first in time; batch 0 fails later but comes first in order,
    # so the job sees the same error as when batches ran one by one.
    fail = {0: provider_error(503), 1: error("invalid_model_output", "bad")}
    with pytest.raises(AppError) as caught:
        await run(env, 2, fail)
    assert caught.value.code == "provider_unavailable"
    sent = [p for p in env.model.payloads if p["task"] == "summarize_batch"]
    assert len(sent) == 2  # Batches waiting for a slot were never sent.
    assert not [p for p in env.model.payloads if p["task"] == "compare"]


@pytest.mark.parametrize(
    ("max_concurrent", "user_concurrent", "expected"),
    [(1, 1, 1), (3, 1, 1), (3, 2, 2), (3, 3, 3), (8, 8, 3)],
)
def test_batch_concurrency_never_exceeds_quota_broker(max_concurrent, user_concurrent, expected):
    from youtube_backend.config import Settings

    from youtube_answers.config import AnswerSettings
    from youtube_answers.integration import batch_limited

    # A batch the broker cannot admit is denied with quota_wait and requeues the
    # whole job for a minute, so the cap must follow the broker's limits.
    backend = Settings(
        _env_file=None,
        gemini_max_concurrent=max_concurrent,
        gemini_user_concurrent=user_concurrent,
    )
    config = AnswerSettings(_env_file=None, answer_batch_concurrency=3)
    assert batch_limited(config, backend).answer_batch_concurrency == expected
    assert config.answer_batch_concurrency == 3, "caller's settings stay unchanged"
