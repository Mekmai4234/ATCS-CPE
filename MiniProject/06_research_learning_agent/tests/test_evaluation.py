import json

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.errors import AppError

from youtube_agent.evaluation import Dataset, default_dataset, evaluate

DATASET = default_dataset()


@pytest.mark.parametrize("legacy_test", [False, True])
async def test_acceptance_report_covers_tasks_latency_usage_and_pending_quality(
    tmp_path, monkeypatch, legacy_test
):
    # Offline mode never sends this key anywhere and must not include it in reports.
    monkeypatch.setenv("GEMINI_API_KEY", "evaluation-secret-never-report")
    previous_actor = actor_id.get()
    report = await evaluate(DATASET, tmp_path / "isolated", legacy_test=legacy_test)
    assert actor_id.get() == previous_actor
    assert report["contract_passed"]
    assert report["mode"] == "offline-fixture"
    assert report["authorization_mode"] == (
        "isolated-legacy-test" if legacy_test else "isolated-member-fixture"
    )
    if not legacy_test:
        database = db.Database(f"sqlite:///{(tmp_path / 'isolated' / 'app.db').as_posix()}")
        try:
            with database.read() as connection:
                owners = connection.scalars(sa.select(db.users.c.user_id)).all()
                assert len(owners) == 1
                assert set(connection.scalars(sa.select(db.jobs.c.owner_id))) == set(owners)
                assert set(connection.scalars(sa.select(db.artifacts.c.owner_id))) == set(owners)
        finally:
            database.close()
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


async def test_live_legacy_mode_is_rejected_before_state_creation(tmp_path):
    state = tmp_path / "unused"
    with pytest.raises(ValueError, match="Legacy test mode"):
        await evaluate(DATASET, state, live=True, legacy_test=True)
    assert not state.exists()


async def test_auth_failure_cannot_be_counted_as_expected_failure(tmp_path, monkeypatch):
    async def deny(*args):
        raise AppError("authentication_required", "Missing evaluation actor", 401)

    monkeypatch.setattr("youtube_agent.evaluation.OfflineModel.decide", deny)
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    case = next(case for case in data["cases"] if case["operation"] == "research")
    case["expected_states"] = ["failed"]
    data["cases"] = [case]
    dataset = tmp_path / "denied.json"
    dataset.write_text(json.dumps(data), encoding="utf-8")
    report = await evaluate(dataset, tmp_path / "denied-state")
    assert report["cases"][0]["error_code"] == "authentication_required"
    assert not report["contract_passed"] and not report["cases"][0]["contract_passed"]


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
