"""Fresh local sources attach explicitly; private orphaned sources stay private."""

import copy

import pytest
import sqlalchemy as sa
from test_documents import document
from test_identity import VIDEO, login
from test_identity import identity as identity

from youtube_backend import database as db
from youtube_backend.document_store import publish


@pytest.mark.parametrize("seeded", [True, False])
def test_first_attachment_requires_trusted_local_seed(identity, seeded):
    env = identity
    client, _ = login(env, "reader")
    value = document()
    value["video_id"] = VIDEO
    publish(env.db, value, create_missing=True)
    if not seeded:
        with env.db.write() as c:
            record = c.scalar(sa.select(db.documents["versions"].c.data))
            c.execute(
                db.documents["versions"]
                .update()
                .values(data={**record, "local_library_import": False})
            )
    else:
        # Operator updates retain the source's trusted first-attachment policy.
        updated = copy.deepcopy(value)
        updated["sha256"] = "b" * 64
        publish(env.db, updated)
    with env.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.user_videos)) == 0
    result = client.post("/api/videos/import", json={"urls": [f"https://youtu.be/{VIDEO}"]})
    assert result.status_code == 202, result.text
    item = result.json()["jobs"][0]
    if seeded:
        assert item["outcome"] == "accepted"
        with env.db.read() as c:
            job = c.execute(sa.select(db.jobs)).mappings().one()
            assert job["kind"] == "attach" and job["state"] == "completed"
            assert c.scalar(sa.select(sa.func.count()).select_from(db.user_videos)) == 1
    else:
        assert item["error_code"] == "source_unavailable"
        with env.db.read() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(db.user_videos)) == 0
