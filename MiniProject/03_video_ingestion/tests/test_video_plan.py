import pytest
from youtube_backend.schemas import Source

from youtube_ingestion.video_plan import VideoPlan


def test_only_canonical_scoped_youtube_inputs_and_bounded_focus():
    source = Source(video_id="dQw4w9WgXcQ", generation=1, transcript_version="v1")
    plan = VideoPlan(source, end_seconds=600)
    assert plan.uri == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert plan.focus(10, 20).fps == 3
    for start, end in [(-1, 10), (0, 21), (590, 610)]:
        with pytest.raises(ValueError):
            plan.focus(start, end)


@pytest.mark.parametrize(
    "question,start,end,fps",
    [
        ("ในภาพมีอะไร", 0, None, 0.25),
        ("ดูช่วง01:20:30", 4825, 4845, 3),
        ("ดูช่วง01:20", 75, 95, 3),
        ("ดูช่วง00:00", 0, 15, 3),
        ("ดูช่วง02:00:00", 7180, 7200, 3),
        ("ช่วง01:00ถึง04:00", 60, 240, 0.25),
        ("ช่วง 01:00-01:10", 60, 70, 3),
        ("from 00:59:50 to 01:00:10", 3590, 3610, 3),
    ],
)
def test_time_question_selects_exact_requested_scope(question, start, end, fps):
    plan = VideoPlan.from_question(
        Source(video_id="dQw4w9WgXcQ", generation=1, transcript_version="v1"), question
    )
    assert (plan.start_seconds, plan.end_seconds, plan.fps) == (start, end, fps)


@pytest.mark.parametrize(
    "question",
    [
        "เวลา01:20:",
        "เวลา:01:20",
        "เวลา01:60",
        "เวลา1:2",
        "ช่วง01:00:00:10",
        "เวลา-00:10",
        "เวลา02:00:01",
        "ช่วง04:00ถึง01:00",
        "ช่วง00:10ถึง00:10",
        "ช่วง00:10ถึง-00:20",
        "เทียบ00:10กับ04:00",
        "00:10 00:20 00:30",
    ],
)
def test_invalid_or_ambiguous_time_does_not_silently_pick_a_prefix(question):
    from youtube_backend.errors import AppError

    with pytest.raises(AppError):
        VideoPlan.from_question(
            Source(video_id="dQw4w9WgXcQ", generation=1, transcript_version="v1"), question
        )
