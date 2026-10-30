from youtube_backend.schemas import Segment

from youtube_ingestion.coverage import caption_coverage


def segment(start, duration):
    return Segment(
        segment_id=str(start), text="คำพูด", start_seconds=start, duration_seconds=duration
    )


def test_overlaps_do_not_create_false_gaps():
    report = caption_coverage([segment(12, 2), segment(0, 10), segment(8, 5)])
    assert report["uncovered_intervals"] == []
    assert report["speech_completeness_verified"] is False


def test_leading_internal_and_known_trailing_intervals():
    report = caption_coverage([segment(5, 2), segment(15, 2)], duration_seconds=25)
    assert report["uncovered_intervals"] == [(0, 5), (7, 15), (17, 25)]
    assert report["duration_known"] is True
    assert caption_coverage([segment(5, 2)])["uncovered_intervals"] == [(0, 5)]
