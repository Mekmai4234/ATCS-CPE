import json

import pytest
from pydantic import ValidationError

from youtube_agent.evaluation import Dataset, default_dataset, evaluate

DATASET = default_dataset()


async def test_acceptance_report_covers_tasks_latency_usage_and_pending_quality(
    tmp_path, monkeypatch
):
    # Offline mode never sends this key anywhere and must not include it in reports.
    monkeypatch.setenv("GEMINI_API_KEY", "evaluation-secret-never-report")
    report = await evaluate(DATASET, tmp_path / "isolated")
    assert report["contract_passed"]
    assert report["mode"] == "offline-fixture"
    assert report["provenance"] == "synthetic"
    assert report["semantic_quality_verified"] is False
    assert len(report["cases"]) == 6
    assert {c["id"] for c in report["cases"]} >= {"quiz-th", "flashcards-en", "study-plan"}
    for case in report["cases"]:
        assert case["wall_latency_ms"] >= 0
        assert case["provider_metadata"]["provider"] in {"fixture", "none"}
        assert "usage" in case["provider_metadata"]
        assert case["manual_review"]["required"] and case["manual_review"]["passed"] is None
    assert next(c for c in report["cases"] if c["id"] == "step-limit")["state"] == "partial"
    assert "evaluation-secret-never-report" not in json.dumps(report)


async def test_existing_state_is_never_reused_or_mutated(tmp_path):
    state = tmp_path / "existing"
    state.mkdir()
    marker = state / "keep.txt"
    marker.write_text("keep me", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await evaluate(DATASET, state)
    assert marker.read_text(encoding="utf-8") == "keep me"
    assert sorted(p.name for p in state.iterdir()) == ["keep.txt"]


@pytest.mark.parametrize("failure", ["scope", "duplicate", "request"])
def test_dataset_is_validated_before_processing(failure):
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    if failure == "scope":
        data["cases"][0]["request"]["scope"]["video_ids"] = ["aaaaaaaaaaa"]
    elif failure == "duplicate":
        data["cases"].append(data["cases"][0])
    else:
        data["cases"][0]["request"]["unexpected_owner"] = "not-allowed"
    with pytest.raises(ValidationError):
        Dataset.model_validate(data)
