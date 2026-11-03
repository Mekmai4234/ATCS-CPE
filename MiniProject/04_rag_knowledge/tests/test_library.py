import time

import pytest
from conftest import VIDEO_A, VIDEO_B, transcript
from test_authorized_sources import accounts, actor, attach, query
from test_media_rag import bundle
from youtube_backend import database as db
from youtube_backend.errors import AppError
from youtube_backend.media import MediaStore
from youtube_backend.repository import digest
from youtube_backend.schemas import Segment
from youtube_backend.video_evidence import VERSION

__all__ = ["accounts"]


def seed(env, source, *, owner="a", expires=None, model=None):
    # Explicit storage fixture, not a real inference or a billing attestation.
    observation = dict(
        id="v1",
        kind="visual",
        text="A red card is shown; this is a replay, not a second event.",
        start_seconds=2,
        end_seconds=4,
    )
    cache_id = digest([owner, source.model_dump(), observation])
    with env.db.write() as c:
        c.execute(
            db.v2["cache"]
            .insert()
            .values(
                cache_id=cache_id,
                owner_id=owner,
                video_id=source.video_id,
                generation=source.generation,
                evidence_version=source.transcript_version,
                prompt_version=VERSION,
                model=model or env.settings.llm_model,
                input_hash="a" * 64,
                expires_at=expires or time.time() + 3600,
                data=dict(source=source.model_dump(), observations=[observation]),
            )
        )
    return cache_id


async def test_new_questions_reuse_full_observations_without_embeddings(accounts, monkeypatch):
    env = accounts
    seed(env, env.source_a)
    task = query(env, "a", VIDEO_A)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Library lookup must not call remote embeddings")

    monkeypatch.setattr(env.rag.embedder, "embed", forbidden)
    library = env.rag.evidence_library()
    for question in ("red card", "replay second event"):
        result = await library.search(question, task.sources, task.ctx, kinds=["video"])
        assert len(result.items) == 1
        record = result.items[0]
        assert record.kind == "video" and "not a second event" in record.text
        assert record.citation["kind"] == "video"
        assert record.provenance["model"] == env.settings.llm_model
    assert not (await library.search("cooking rice", task.sources, task.ctx, kinds=["video"])).items


@pytest.mark.parametrize("vision_model", ["", "approved-vision-model"])
async def test_catalogue_uses_effective_vision_model_and_rejects_old_model(accounts, vision_model):
    env = accounts
    env.settings.vision_model = vision_model
    effective = vision_model or env.settings.llm_model
    seed(env, env.source_a, model=effective)
    task = query(env, "a", VIDEO_A)
    result = await env.rag.evidence_library().search(
        "red card", task.sources, task.ctx, kinds=["video"]
    )
    assert len(result.items) == 1 and result.items[0].provenance["model"] == effective
    env.settings.vision_model = "another-vision-model"
    assert not (
        await env.rag.evidence_library().search("red card", task.sources, task.ctx, kinds=["video"])
    ).items


async def test_cross_owner_expiry_and_source_revocation(accounts):
    env = accounts
    seed(env, env.source_a)
    with actor("b"):
        attached = attach(env, "b")
        from youtube_backend.worker import Worker

        await Worker(env.repo, env.adapters, env.settings).run_once(attached["job_id"])
    other = query(env, "b", VIDEO_A)
    library = env.rag.evidence_library()
    assert not (await library.search("red card", other.sources, other.ctx, kinds=["video"])).items
    task = query(env, "a", VIDEO_A)
    with env.db.write() as c:
        c.execute(db.v2["cache"].update().values(expires_at=time.time() - 1))
    assert not (await library.search("card", task.sources, task.ctx, kinds=["video"])).items
    with env.db.write() as c:
        c.execute(db.user_videos.delete().where(db.user_videos.c.user_id == "a"))
    with pytest.raises(AppError):
        await library.search("card", task.sources, task.ctx)


async def test_multiclip_balance_time_filter_and_transcript_provenance(accounts):
    env = accounts
    with actor("a"):
        item = env.repo.import_urls([f"https://youtu.be/{VIDEO_B}"])[0]
        from youtube_backend.worker import Worker

        await Worker(env.repo, env.adapters, env.settings).run_once(item["job_id"])
    task = query(env, "a", VIDEO_A, VIDEO_B)
    result = await env.rag.evidence_library().search(
        "Embeddings",
        task.sources,
        task.ctx,
        kinds=["transcript"],
        limit=2,
        start_seconds=10,
        end_seconds=28,
        neighbors=1,
    )
    assert {r.source.video_id for r in result.items} == {VIDEO_A, VIDEO_B}
    assert all(r.kind == "transcript" and r.provenance["segment_ids"] for r in result.items)
    assert all(r.start_seconds <= 28 and r.end_seconds >= 10 for r in result.items)


async def test_ocr_keeps_snapshot_and_does_not_become_transcript(accounts):
    env = accounts
    with actor("a"):
        item = MediaStore(env.repo).enqueue(VIDEO_A)
    job = env.repo.claim(item["job_id"])
    MediaStore(env.repo).publish(env.context(job), bundle())
    env.repo.finish(job["job_id"], job["lease_token"], {})
    task = query(env, "a", VIDEO_A)
    result = await env.rag.evidence_library().search(
        "ห้องเรียน", task.sources, task.ctx, kinds=["ocr"]
    )
    assert result.items and result.items[0].kind == "ocr"
    assert result.items[0].citation["source"]["kind"] == "ocr"
    assert "transcript_version" not in result.items[0].citation["source"]


async def test_changed_generation_and_cancelled_execution_fail_closed(accounts):
    env = accounts
    task = query(env, "a", VIDEO_A)
    with env.db.write() as c:
        c.execute(db.videos.update().where(db.videos.c.video_id == VIDEO_A).values(generation=2))
    with pytest.raises(AppError):
        await env.rag.evidence_library().search("card", task.sources, task.ctx)


async def test_late_transcript_match_is_filtered_before_collection_limit(accounts):
    env = accounts
    video = "LateQuery01"
    value = transcript(video).model_copy(
        update={
            "segments": [
                Segment(
                    segment_id=f"s{i}",
                    text="zirconium final detail"
                    if i == 29
                    else "Introduction background without the target topic " * 3,
                    start_seconds=i * 20,
                    duration_seconds=10,
                )
                for i in range(30)
            ]
        }
    )
    with actor("a"):
        await env.ready(video, value=value)
    task = query(env, "a", video)
    result = await env.rag.evidence_library().search(
        "zirconium",
        task.sources,
        task.ctx,
        kinds=["transcript"],
        max_records=1,
        limit=1,
        start_seconds=570,
        end_seconds=600,
    )
    assert len(result.items) == 1 and "zirconium" in result.items[0].text
    # Preserve the original overlapping chunk interval instead of clipping its citation.
    assert result.items[0].start_seconds <= 600 and result.items[0].end_seconds >= 570


@pytest.mark.parametrize(
    "extra", [{"start_seconds": float("nan")}, {"limit": 0}, {"neighbors": 3}, {"kinds": ["fake"]}]
)
async def test_library_rejects_unbounded_or_invalid_requests(accounts, extra):
    task = query(accounts, "a", VIDEO_A)
    with pytest.raises(AppError):
        await accounts.rag.evidence_library().search("card", task.sources, task.ctx, **extra)


@pytest.mark.parametrize("start,end,expected", [(0, 40, True), (40, 50, False), (600, 610, False)])
async def test_transcript_time_window_requires_positive_overlap(accounts, start, end, expected):
    task = query(accounts, "a", VIDEO_A)
    result = await accounts.rag.evidence_library().search(
        "RAG",
        task.sources,
        task.ctx,
        kinds=["transcript"],
        start_seconds=start,
        end_seconds=end,
        neighbors=2,
    )
    assert bool(result.items) is expected
    assert all(r.end_seconds > start and r.start_seconds < end for r in result.items)
    assert any("full original intervals" in note for note in result.notes)


@pytest.mark.parametrize("start,end,expected", [(4, 8, False), (0, 2, False), (3, 4, True)])
async def test_video_observation_time_boundary_and_original_citation(
    accounts, start, end, expected
):
    seed(accounts, accounts.source_a)
    task = query(accounts, "a", VIDEO_A)
    result = await accounts.rag.evidence_library().search(
        "red card",
        task.sources,
        task.ctx,
        kinds=["video"],
        start_seconds=start,
        end_seconds=end,
        neighbors=1,
    )
    assert bool(result.items) is expected
    if result.items:
        assert (result.items[0].start_seconds, result.items[0].end_seconds) == (2, 4)


@pytest.mark.parametrize("lower,upper,expected", [(2, 4, True), (0, 2, False), (3, 4, False)])
async def test_ocr_point_uses_half_open_time_window(accounts, lower, upper, expected):
    # Pure boundary contract for instant observations; source/owner lifecycle covered above.
    from youtube_rag.library import overlaps

    assert overlaps(2, 2, lower, upper) is expected


async def test_current_question_alone_does_not_match_unrelated_topic(accounts):
    task = query(accounts, "a", VIDEO_A)
    library = accounts.rag.evidence_library()
    assert (await library.search("RAG", task.sources, task.ctx, kinds=["transcript"])).items
    assert not (
        await library.search(
            "photosynthesis", task.sources, task.ctx, kinds=["transcript"], neighbors=1
        )
    ).items
