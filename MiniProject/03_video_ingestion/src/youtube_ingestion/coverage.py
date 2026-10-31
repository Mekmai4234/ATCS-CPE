"""Caption timing diagnostics; uncovered time does not prove missing speech."""

import math


def caption_coverage(segments, *, duration_seconds=None, gap_seconds=5.0):
    if not math.isfinite(gap_seconds) or gap_seconds <= 0:
        raise ValueError("gap_seconds must be positive")
    if duration_seconds is not None and (
        not math.isfinite(duration_seconds) or duration_seconds < 0
    ):
        raise ValueError("Duration must be finite and nonnegative")
    end = 0.0
    gaps = []
    for segment in sorted(segments, key=lambda item: item.start_seconds):
        start = segment.start_seconds
        if start - end >= gap_seconds:
            gaps.append((end, start))
        end = max(end, start + segment.duration_seconds)
    if duration_seconds is not None:
        if duration_seconds < end:
            raise ValueError("Duration precedes caption end")
        if duration_seconds - end >= gap_seconds:
            gaps.append((end, duration_seconds))
    return {
        "uncovered_intervals": gaps,
        "observed_end_seconds": end,
        "duration_known": duration_seconds is not None,
        "speech_completeness_verified": False,
    }
