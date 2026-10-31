"""Offline feedback rollout readiness; never deploys or attests for a human."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

CHECKS = (
    "full_floating_history_feedback",
    "feedback_failed_save_and_stale_response",
    "warning_block_ack_resume_replay",
    "withheld_all_public_surfaces",
    "member_admin_capability_session_boundaries",
    "exact_pairs_and_audit",
    "notice_and_privacy_text_human_reviewed",
    "retention_deletion_ledger",
    "paired_backup_migrate_restore",
    "purge_schedule_verified",
    "responsive_accessibility_screenshots",
)
JOBS = {
    "python (ubuntu-latest)",
    "python (windows-latest)",
    "frontend",
    "packaging",
    "local-media-tools",
}


def template(source):
    return dict(
        schema=1,
        source_revision=source["revision"],
        source_sha256=source["source_sha256"],
        reviewed_by=None,
        reviewed_at=None,
        expires_at=None,
        signals_in_release=False,
        checks={name: None for name in (*CHECKS, "producer05_signals_integrated")},
    )


def check(source, evidence=None, ci=None, quality_report=None, *, now=None):
    now = now or datetime.now(UTC)
    evidence, ci = evidence or {}, ci or {}
    blockers = []
    if source.get("mode") != "checkout" or source.get("dirty") is not False:
        blockers.append("clean_actual_checkout_required")
    if evidence.get("schema") != 1 or any(
        evidence.get(key) != source.get(source_key)
        for key, source_key in (("source_revision", "revision"), ("source_sha256", "source_sha256"))
    ):
        blockers.append("exact_source_review_evidence_required")
    try:
        reviewed, expires = [
            datetime.fromisoformat(evidence[key]) for key in ("reviewed_at", "expires_at")
        ]
        if not reviewed.tzinfo or not expires.tzinfo or not reviewed <= now < expires:
            raise ValueError("Invalid review interval")
        if (expires - reviewed).total_seconds() > 7 * 86400:
            raise ValueError("Review interval too long")
        reviewer = evidence["reviewed_by"]
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("Reviewer missing")
    except (KeyError, TypeError, ValueError):
        blockers.append("dated_human_integration_review_required")
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), dict) else {}
    blockers.extend(name + "_pending" for name in CHECKS if checks.get(name) is not True)
    if type(evidence.get("signals_in_release")) is not bool:
        blockers.append("signal_release_scope_required")
    if (
        evidence.get("signals_in_release") is True
        and checks.get("producer05_signals_integrated") is not True
    ):
        blockers.append("producer05_integration_pending")
    jobs = {job.get("name"): job for job in ci.get("jobs", []) if isinstance(job, dict)}
    if (
        ci.get("status") != "completed"
        or ci.get("conclusion") != "success"
        or ci.get("headSha") != source.get("revision")
    ):
        blockers.append("successful_exact_revision_ci_required")
    if any(
        jobs.get(name, {}).get("conclusion") != "success"
        or jobs.get(name, {}).get("status") != "completed"
        for name in JOBS
    ):
        blockers.append("all_five_ci_jobs_required")
    gold_ready = isinstance(quality_report, dict) and quality_report.get("gold_ready") is True
    return dict(
        feedback_release_ready=not blockers,
        human_gold_ready=gold_ready,
        live_semantic_acceptance=False,
        blockers=blockers,
        source_revision=source.get("revision"),
        source_sha256=source.get("source_sha256"),
        production_migrated=False,
        capability_enabled=False,
        deployment_performed=False,
        attestation_created=False,
        provider_calls=0,
    )


def main():
    from evidence_review import review_gate
    from source import context

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", action="store_true")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--ci-report", type=Path)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--write-template", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = context(args.checkout)
    if args.write_template:
        with args.write_template.open("x", encoding="utf-8") as stream:
            json.dump(template(source), stream, indent=2)

    def load(path):
        return json.loads(path.read_text(encoding="utf-8")) if path else None

    gold_path = args.gold or Path(__file__).parents[1] / "fixtures/video_review_36.json"
    report = check(source, load(args.evidence), load(args.ci_report), review_gate(load(gold_path)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(not report["feedback_release_ready"])


if __name__ == "__main__":
    raise SystemExit(main())
