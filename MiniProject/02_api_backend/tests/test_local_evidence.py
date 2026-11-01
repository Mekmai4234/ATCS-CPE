from test_identity import VIDEO, login, ready
from test_identity import identity as identity


def test_local_excerpts_are_owned_and_do_not_create_work(identity):
    import sqlalchemy as sa

    from youtube_backend import database as db

    env = identity
    client, _ = login(env, "a")
    ready(env, client)
    with env.db.read() as c:
        before = c.scalar(sa.select(sa.func.count()).select_from(db.jobs))
    body = {"question": "RAG", "scope": {"video_ids": [VIDEO]}}
    response = client.post("/api/evidence/search", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["provider_calls"] == 0
    assert response.json()["kind"] == "transcript_excerpts"
    assert response.json()["items"]
    other, _ = login(env, "b")
    assert other.post("/api/evidence/search", json=body).status_code in {403, 404}
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == before
