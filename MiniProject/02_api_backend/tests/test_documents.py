import copy

import pytest
import sqlalchemy as sa
from conftest import VIDEO_A
from pydantic import ValidationError

from youtube_backend import database as db
from youtube_backend.document_store import publish, read, verify_citation
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.schemas import Citation, Source


def document():
    return dict(
        document_id="test-song",
        video_id=VIDEO_A,
        language="th",
        sha256="a" * 64,
        relative_path="test.txt",
        metadata={"single": "Test song", "artist": "Singer"},
        timing_status="user_supplied_unverified",
        import_version="test-v1",
        segments=[
            dict(
                segment_id="line:3",
                line=3,
                text="good night",
                start_seconds=19,
                end_seconds=None,
                end_method="unknown",
            )
        ],
    )


def execution(env):
    job = env.repo.enqueue("chat", {"question": "ใครร้อง", "scope": {"video_ids": [VIDEO_A]}})
    job = env.repo.claim(job["job_id"])
    ctx = ExecutionContext(
        env.repo, job["job_id"], job["lease_token"], job["deadline_at"], env.settings
    )
    return job, ctx, [Source.model_validate(s) for s in job["payload"]["sources"]]


def test_document_publication_is_idempotent_and_keeps_caption_version(ready):
    with ready.db.read() as c:
        before = dict(
            c.execute(sa.select(db.videos).where(db.videos.c.video_id == VIDEO_A)).mappings().one()
        )
    first = publish(ready.db, document())
    assert publish(ready.db, document()) == {**first, "imported": False}
    with ready.db.read() as c:
        assert (
            dict(
                c.execute(sa.select(db.videos).where(db.videos.c.video_id == VIDEO_A))
                .mappings()
                .one()
            )
            == before
        )
        assert c.scalar(sa.select(sa.func.count()).select_from(db.documents["versions"])) == 1


def test_start_only_and_metadata_citations_checked_against_frozen_document(ready):
    receipt = publish(ready.db, document())
    job, context, sources = execution(ready)
    assert len(read(context, sources)) == 1
    citation = Citation(
        citation_id="1",
        chunk_id="line:3",
        video_id=VIDEO_A,
        title="",
        kind="document_transcript",
        document_id="test-song",
        document_version=receipt["version"],
        source_hash="a" * 64,
        document_line=3,
        start_seconds=19,
    )
    with ready.db.read() as c:
        verify_citation(ready.repo, c, job, citation)
    assert citation.end_seconds is None and citation.url.endswith("&t=19s")
    metadata = citation.model_copy(
        update={
            "kind": "document_metadata",
            "chunk_id": "metadata:single",
            "metadata_field": "single",
            "start_seconds": None,
            "document_line": None,
        }
    )
    with ready.db.read() as c:
        verify_citation(ready.repo, c, job, metadata)
    assert "&t=" not in metadata.url
    with ready.db.read() as c, pytest.raises(AppError, match="identity/time"):
        verify_citation(ready.repo, c, job, citation.model_copy(update={"end_seconds": 20}))


def test_activation_invalidates_inflight_job_and_preserves_old_version(ready):
    old = publish(ready.db, document())
    _, context, sources = execution(ready)
    changed = copy.deepcopy(document())
    changed["sha256"] = "b" * 64
    changed["segments"][0]["text"] = "New text"
    new = publish(ready.db, changed)
    assert old["version"] != new["version"]
    with pytest.raises(AppError) as exc:
        read(context, sources)
    assert exc.value.code == "source_changed"
    with ready.db.read() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.documents["versions"])) == 2


def test_invalid_version_cannot_replace_ready_document(ready):
    first = publish(ready.db, document())
    broken = copy.deepcopy(document())
    broken["segments"][0]["end_seconds"] = 0
    with pytest.raises(ValueError):
        publish(ready.db, broken)
    with ready.db.read() as c:
        assert c.scalar(sa.select(db.documents["active"].c.version)) == first["version"]


def test_missing_clip_does_not_gain_library_access(ready):
    value = document()
    value["video_id"] = "C0DXctGPWxw"
    with pytest.raises(AppError) as exc:
        publish(ready.db, value)
    assert exc.value.code == "video_not_ready"


def test_explicit_local_allowlist_can_initialize_a_source_without_granting_membership(env):
    value = document()
    value["video_id"] = "C0DXctGPWxw"
    first = publish(env.db, value, create_missing=True)
    with env.db.read() as c:
        video = (
            c.execute(sa.select(db.videos).where(db.videos.c.video_id == value["video_id"]))
            .mappings()
            .one()
        )
        assert video["status"] == "ready"
        assert video["indexed_version"] == value["sha256"]
        assert c.scalar(sa.select(sa.func.count()).select_from(db.user_videos)) == 0
        assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == 0
    assert publish(env.db, value, create_missing=True) == {**first, "imported": False}


def test_document_page_authorization_and_old_version_retention(ready):
    import time

    from youtube_backend.auth import actor_id
    from youtube_backend.document_store import source_page

    old = publish(ready.db, document())
    changed = copy.deepcopy(document())
    changed["metadata"]["single"] = "New title"
    publish(ready.db, changed)
    with ready.db.write() as c:
        for user in ("reader", "foreign"):
            c.execute(
                db.users.insert().values(
                    user_id=user,
                    google_sub=user,
                    role="user",
                    status="active",
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )
        c.execute(
            db.user_videos.insert().values(
                user_id="reader", video_id=VIDEO_A, created_at=time.time()
            )
        )
    ready.settings.auth_enabled = True
    token = actor_id.set("reader")
    try:
        assert source_page(ready.repo, VIDEO_A, old["version"])["metadata"]["single"] == "Test song"
        actor_id.set("foreign")
        with pytest.raises(AppError) as exc:
            source_page(ready.repo, VIDEO_A, old["version"])
        assert exc.value.status_code == 404
    finally:
        actor_id.reset(token)


def test_populated_document_migration_cannot_be_silently_dropped(ready):
    from alembic import command

    from youtube_backend.migration import alembic_config

    publish(ready.db, document())
    with ready.db.engine.begin() as c, pytest.raises(RuntimeError, match="paired backup"):
        command.downgrade(alembic_config(c), "0004")


@pytest.mark.parametrize(
    "kind, start, end",
    [("transcript", None, None), ("video", 1, None), ("document_metadata", 0, None)],
)
def test_citations_cannot_invent_time_shape(kind, start, end):
    with pytest.raises(ValidationError):
        Citation(
            citation_id="1",
            chunk_id="x",
            video_id=VIDEO_A,
            title="",
            kind=kind,
            start_seconds=start,
            end_seconds=end,
            document_id="test-song",
            document_version="a" * 64,
            source_hash="a" * 64,
            metadata_field="single",
        )
