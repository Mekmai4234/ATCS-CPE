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


def test_duplicate_and_overlapping_timestamps_do_not_inflate_covered_duration():
    items = [segment(0, 10), segment(0, 10), segment(8, 5), segment(20, 2)]
    report = caption_coverage(items)
    assert report["segment_count"] == 4
    assert report["duplicate_segments"] == 1
    assert report["overlapping_segments"] == 2
    assert report["covered_seconds"] == 15
    assert report["uncovered_intervals"] == [(13, 20)]
    assert report["duration_known"] is False
    assert len(items) == 4  # Diagnostic only: never silently edit source evidence.


def test_same_words_at_different_times_are_not_duplicates():
    report = caption_coverage([segment(0, 2), segment(2, 2)])
    assert report["duplicate_segments"] == 0
    assert report["covered_seconds"] == 4
