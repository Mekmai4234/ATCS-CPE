"""Offline human-review gate and latency summaries; never equate schemas with accuracy."""

import argparse
import hashlib
import json
import math
from pathlib import Path

CATEGORIES = {"speech", "screen_text", "visual", "sequence", "count", "insufficient"}
SCENARIOS = {"first_question", "same_question", "new_question_same_clip"}
STAGES = ("retrieval_ms", "queue_ms", "provider_ms", "total_ms")


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def review_gate(dataset):
    reasons = []
    cases = dataset.get("cases", [])
    if not 30 <= len(cases) <= 50:
        reasons.append("30_to_50_cases_required")
    if len({c.get("id") for c in cases}) != len(cases):
        reasons.append("duplicate_case_ids")
    if not CATEGORIES <= {c.get("category") for c in cases}:
        reasons.append("missing_question_categories")
    if not {"th", "en"} <= {c.get("language") for c in cases}:
        reasons.append("thai_and_english_required")
    for case in cases:
        review = case.get("review") or {}
        # Reviewed gold and referenced source version are independent of model output.
        if (
            review.get("status") != "human_reviewed"
            or not review.get("reviewer")
            or not review.get("reviewed_at")
            or not case.get("expected_answer")
            or not case.get("source_version")
            or not case.get("references")
            or review.get("case_sha256")
            != fingerprint({k: v for k, v in case.items() if k != "review"})
        ):
            reasons.append(f"human_gold_required:{case.get('id', 'unknown')}")
            continue
        for ref in case["references"]:
            start, end = ref.get("start_seconds"), ref.get("end_seconds")
            if (
                not isinstance(start, (int, float))
                or isinstance(start, bool)
                or not isinstance(end, (int, float))
                or isinstance(end, bool)
                or not math.isfinite(start)
                or not math.isfinite(end)
                or not 0 <= start < end
                or ref.get("video_id") not in case.get("video_ids", [])
            ):
                reasons.append(f"invalid_reference:{case['id']}")
    return dict(
        gold_ready=not reasons,
        semantic_quality_verified=False,
        reasons=reasons,
        case_count=len(cases),
        source="human_assertions_not_independently_verified",
    )


def latency_summary(samples, *, minimum=20):
    groups = {}
    for sample in samples:
        if sample.get("scenario") not in SCENARIOS:
            raise ValueError("Unknown timing scenario")
        for key in STAGES:
            value = sample.get(key)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("Timings must be measured nonnegative finite values")
        if sample.get("total_ms") is None:
            raise ValueError("Total wall time is required")
        group = (
            sample["scenario"],
            sample.get("duration_class", "unknown"),
            sample.get("mode", "default"),
        )
        groups.setdefault(group, []).append(sample)
    results = []
    for group, rows in groups.items():
        stages = {}
        for stage in STAGES:
            values = sorted(r[stage] for r in rows if r.get(stage) is not None)
            stages[stage] = dict(n=len(values), p50_ms=None, p95_ms=None)
            # Do not publish percentiles for tiny or incompletely instrumented groups.
            if len(values) >= minimum:
                stages[stage].update(
                    p50_ms=values[math.ceil(len(values) * 0.5) - 1],
                    p95_ms=values[math.ceil(len(values) * 0.95) - 1],
                )
        results.append(
            dict(
                scenario=group[0],
                duration_class=group[1],
                mode=group[2],
                n=len(rows),
                stages=stages,
                enough_samples=len(rows) >= minimum,
            )
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--timings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text("utf-8"))
    result = review_gate(dataset)
    result["dataset_sha256"] = fingerprint(dataset)
    result["latency"] = (
        latency_summary(json.loads(args.timings.read_text("utf-8"))) if args.timings else []
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "reasons"}))
    raise SystemExit(0 if result["gold_ready"] else 2)


if __name__ == "__main__":
    main()
