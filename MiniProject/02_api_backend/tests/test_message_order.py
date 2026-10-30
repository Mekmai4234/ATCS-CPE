import time

import sqlalchemy as sa
from conftest import VIDEO_A, chat_body, import_ready

from youtube_backend import database as db


async def test_equal_host_clock_keeps_multiple_turns_in_causal_order(env, monkeypatch):
    await import_ready(env, VIDEO_A)
    instant = time.time()
    monkeypatch.setattr("youtube_backend.repository.time.time", lambda: instant)
    first = env.client.post("/api/chat", json=chat_body()).json()
    conversation = first["conversation_id"]
    second = env.client.post("/api/chat", json=chat_body(conversation_id=conversation))
    assert second.status_code == 200, second.text
    history = env.client.get(f"/api/conversations/{conversation}").json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user", "assistant"]
    assert all(m["citations"] for m in history["messages"] if m["role"] == "assistant")
    with env.db.read() as c:
        times = (
            c.execute(
                sa.select(db.messages.c.created_at)
                .where(db.messages.c.conversation_id == conversation)
                .order_by(db.messages.c.created_at)
            )
            .scalars()
            .all()
        )
    assert len(set(times)) == 4
