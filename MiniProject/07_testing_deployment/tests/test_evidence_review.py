import copy
import json
from pathlib import Path

import pytest
from test_tooling import load
from youtube_backend.errors import AppError


def draft():
    return json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "video_review_36.json").read_text(
            "utf-8"
        )
    )


def test_real_video_question_plan_is_explicitly_unreviewed_and_blocks_release():
    data = draft()
    result = load("evidence_review").review_gate(data)
    assert result["case_count"] == 36 and not result["gold_ready"]
    assert result["semantic_quality_verified"] is False
    assert len({v for c in data["cases"] for v in c["video_ids"]}) == 6
    assert all(c["expected_answer"] is None for c in data["cases"])
    assert len([r for r in result["reasons"] if r.startswith("human_gold_required:")]) == 36


def test_gold_review_is_bound_to_exact_question_answer_and_source_version():
    review = load("evidence_review")
    data = draft()
    for case in data["cases"]:
        case.update(
            expected_answer="[FIXTURE] reviewed answer",
            source_version="fixture-v1",
            references=[dict(video_id=case["video_ids"][0], start_seconds=1, end_seconds=2)],
        )
        case["review"] = dict(
            status="human_reviewed",
            reviewer="fixture-reviewer-not-real-review",
            reviewed_at="2026-10-30T12:00:00+00:00",
            case_sha256=review.fingerprint({k: v for k, v in case.items() if k != "review"}),
        )
    assert review.review_gate(data)["gold_ready"]
    changed = copy.deepcopy(data)
    changed["cases"][0]["expected_answer"] = "Forged new answer"
    assert not review.review_gate(changed)["gold_ready"]
    changed = copy.deepcopy(data)
    changed["cases"][0]["references"][0]["video_id"] = "foreign-clip"
    assert not review.review_gate(changed)["gold_ready"]


def test_latency_separates_cache_new_questions_and_unmeasured_stages():
    review = load("evidence_review")
    samples = [
        dict(
            scenario="new_question_same_clip",
            mode="default",
            duration_class="short",
            total_ms=n,
            provider_ms=n / 2,
            retrieval_ms=None,
            queue_ms=None,
        )
        for n in range(1, 21)
    ]
    samples.append(dict(scenario="same_question", total_ms=0.1))
    result = review.latency_summary(samples)
    new = next(r for r in result if r["scenario"] == "new_question_same_clip")
    assert new["stages"]["total_ms"]["p50_ms"] == 10
    assert new["stages"]["total_ms"]["p95_ms"] == 19
    assert new["stages"]["retrieval_ms"]["p50_ms"] is None
    cached = next(r for r in result if r["scenario"] == "same_question")
    assert not cached["enough_samples"] and cached["stages"]["total_ms"]["p95_ms"] is None
    with pytest.raises(ValueError):
        review.latency_summary([dict(scenario="same_question", total_ms=float("nan"))])


def test_probe_budget_covers_all_endpoints_and_cannot_reset_after_failure(monkeypatch):
    probe = load("learning_probe")
    from youtube_backend.quota import QuotaBroker

    calls = []

    def reserve(self, context, **request):
        calls.append(request["endpoint"])
        if request["endpoint"] == "embedContent":
            raise AppError("provider_timeout", "fixture timeout", 504)
        return "fixture-reservation"

    monkeypatch.setattr(QuotaBroker, "reserve", reserve)
    broker = object.__new__(QuotaBroker)
    budget = probe.ProbeBudget(3, 100)
    with budget.bind():
        broker.reserve(None, endpoint="countTokens", input_tokens=10)
        broker.reserve(None, endpoint="generateContent", input_tokens=50)
        with pytest.raises(AppError, match="timeout"):
            broker.reserve(None, endpoint="embedContent", input_tokens=20)
        with pytest.raises(AppError, match="budget exhausted"):
            broker.reserve(None, endpoint="generateContent", input_tokens=1)
    assert calls == ["countTokens", "generateContent", "embedContent"]
    assert budget.calls == 3 and budget.tokens == 80


def test_probe_rejects_token_overflow_before_reserving():
    probe = load("learning_probe")
    budget = probe.ProbeBudget(2, 10)
    with pytest.raises(AppError, match="budget exhausted"):
        budget.admit(11)
    assert budget.calls == 0


async def test_local_benchmark_keeps_misses_and_distinct_question_scenarios(monkeypatch):
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "evidence_review", load("evidence_review"))
    monkeypatch.setitem(sys.modules, "learning_probe", load("learning_probe"))
    benchmark = load("library_benchmark")
    observed = []

    async def search(question):
        observed.append(question)
        return SimpleNamespace(items=[] if question == "missing fact" else [1], complete=True)

    result = await benchmark.measure(search, ["red card", "missing fact", "replay warning"])
    assert observed.count("red card") == 21
    assert result["samples"][-2]["evidence_hits"] == 0
    assert result["measurement_scope"] == "local_retrieval_only_not_answer_latency"
    assert result["provider_calls"] == 0
    assert result["summary"][-1]["stages"]["total_ms"]["p95_ms"] is None
