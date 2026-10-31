"""Readiness cannot be inferred from merged components, stale CI or fixture success."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from test_tooling import load

release = load("feedback_release")
NOW = datetime(2026, 10, 31, tzinfo=UTC)
SOURCE = dict(mode="checkout", dirty=False, revision="a" * 40, source_sha256="b" * 64)


def reviewed():
    # Synthetic gate-input fixture, not a claim of actual human UI review.
    evidence = release.template(SOURCE)
    evidence.update(
        reviewed_by="fixture-reviewer",
        reviewed_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
    )
    evidence["checks"] = {name: True for name in release.CHECKS}
    ci = dict(
        status="completed",
        conclusion="success",
        headSha=SOURCE["revision"],
        jobs=[dict(name=name, status="completed", conclusion="success") for name in release.JOBS],
    )
    return evidence, ci


def test_missing_integrated_ui_evidence_remains_blocked_and_never_writes_attestation():
    report = release.check(SOURCE, now=NOW)
    assert not report["feedback_release_ready"] and not report["human_gold_ready"]
    assert "notice_and_privacy_text_human_reviewed_pending" in report["blockers"]
    assert not report["attestation_created"] and not report["deployment_performed"]
    assert not report["production_migrated"] and not report["capability_enabled"]


def test_successful_ui_fixture_cannot_be_misreported_as_human_gold_quality():
    evidence, ci = reviewed()
    report = release.check(SOURCE, evidence, ci, now=NOW)
    assert report["feedback_release_ready"] and not report["human_gold_ready"]
    assert not report["live_semantic_acceptance"]


def test_changed_source_or_old_ci_cannot_certify_a_new_release():
    evidence, ci = reviewed()
    for key in ("source_revision", "source_sha256"):
        changed = deepcopy(evidence)
        changed[key] = "0" * 64
        assert not release.check(SOURCE, changed, ci, now=NOW)["feedback_release_ready"]
    assert not release.check(dict(SOURCE, dirty=True), evidence, ci, now=NOW)[
        "feedback_release_ready"
    ]
    assert not release.check(SOURCE, evidence, dict(ci, headSha="old"), now=NOW)[
        "feedback_release_ready"
    ]
    broken = deepcopy(ci)
    broken["jobs"][0]["conclusion"] = "failure"
    assert (
        "all_five_ci_jobs_required" in release.check(SOURCE, evidence, broken, now=NOW)["blockers"]
    )


def test_expired_review_and_truthy_strings_and_optional_signals_are_not_accepted():
    evidence, ci = reviewed()
    evidence["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    assert not release.check(SOURCE, evidence, ci, now=NOW)["feedback_release_ready"]
    evidence, ci = reviewed()
    evidence["checks"][release.CHECKS[0]] = "true"
    assert not release.check(SOURCE, evidence, ci, now=NOW)["feedback_release_ready"]
    evidence, ci = reviewed()
    evidence["signals_in_release"] = True
    assert (
        "producer05_integration_pending" in release.check(SOURCE, evidence, ci, now=NOW)["blockers"]
    )
