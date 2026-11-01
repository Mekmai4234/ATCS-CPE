"""Durable reuse must work before provider access and retain fresh message identity."""

from test_integration import integrated as integrated


async def test_saved_answer_survives_lru_loss_and_never_calls_generation(integrated, monkeypatch):
    env = integrated
    body = {"question": "Explain RAG from this clip", "scope": {"video_ids": ["dQw4w9WgXcQ"]}}
    first = await env.client.post("/api/chat", json=body)
    await env.worker.run_once(first.json()["job_id"])
    original = env.repo.get_job(first.json()["job_id"])
    assert original["state"] == "completed", original
    env.answers.answer_reuse.clear()

    async def forbidden(*args, **kwargs):
        raise AssertionError("Saved read must not request generation or a provider grant")

    monkeypatch.setattr(env.answers, "_answer_uncached", forbidden)
    second = await env.client.post("/api/chat", json=body)
    await env.worker.run_once(second.json()["job_id"])
    restored = env.repo.get_job(second.json()["job_id"])
    assert restored["state"] == "completed", restored
    assert restored["result"]["answer"] == original["result"]["answer"]
    assert restored["result"]["provider_metadata"]["provider"] == "saved-answer-cache"
    assert restored["result"]["assistant_message_id"] != original["result"]["assistant_message_id"]
    assert restored["conversation_id"] != original["conversation_id"]
    third = await env.client.post("/api/chat", json={**body, "question": "A different question"})
    await env.worker.run_once(third.json()["job_id"])
    assert env.repo.get_job(third.json()["job_id"])["state"] == "failed"
