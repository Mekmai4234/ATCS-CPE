import pytest
from youtube_backend.schemas import Source
from youtube_ingestion.video_plan import VideoPlan


def test_only_canonical_scoped_youtube_inputs_and_bounded_focus():
    source = Source(video_id="dQw4w9WgXcQ", generation=1, transcript_version="v1")
    plan = VideoPlan(source)
    assert plan.uri == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert plan.focus(10, 20).fps == 3
    for start, end in [(-1, 10), (0, 21), (590, 610)]:
        with pytest.raises(ValueError):
            plan.focus(start, end)
