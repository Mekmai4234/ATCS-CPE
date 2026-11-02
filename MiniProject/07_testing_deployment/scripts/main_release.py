"""Offline stable-release gate. Consumes evidence; never merges, deploys or creates gold."""

import argparse
import hashlib
import json
from pathlib import Path

from feedback_release import JOBS

REQUIRED = (
    "topic_fallback_owner_regression_http",
    "time_fallback_owner_regression_http",
    "live_features",
    "human_quality",
    "real_import_embeddings",
    "capacity_latency",
    "cache_ownership_feedback",
    "paired_recovery_current_source",
    "runbook",
)
CONDITIONAL = {"public_enabled": "public_auth_tls", "local_model_enabled": "local_model_acceptance"}


def template(source):
    return dict(
        schema=1,
        source_revision=source["revision"],
        source_sha256=source["source_sha256"],
        public_enabled=False,
        local_model_enabled=False,
        checks={
            name: {"status": "pending", "evidence": []}
            for name in (*REQUIRED, *CONDITIONAL.values())
        },
    )


def check(source, manifest, ci, *, evidence_root):
    blockers, files = [], {}
    root = Path(evidence_root).resolve()
    if source.get("mode") != "checkout" or source.get("dirty") is not False:
        blockers.append("clean_checkout_required")
    if manifest.get("schema") != 1 or any(
        manifest.get(key) != source.get(other)
        for key, other in (("source_revision", "revision"), ("source_sha256", "source_sha256"))
    ):
        blockers.append("exact_source_manifest_required")
    jobs = {j.get("name"): j for j in ci.get("jobs", []) if isinstance(j, dict)}
    if (
        ci.get("headSha") != source.get("revision")
        or ci.get("status") != "completed"
        or ci.get("conclusion") != "success"
        or any(
            jobs.get(name, {}).get("status") != "completed"
            or jobs.get(name, {}).get("conclusion") != "success"
            for name in JOBS
        )
    ):
        blockers.append("exact_source_all_five_ci_jobs_required")
    required = list(REQUIRED)
    for flag, name in CONDITIONAL.items():
        if type(manifest.get(flag)) is not bool:
            blockers.append(flag + "_scope_required")
        if manifest.get(flag) is True:
            required.append(name)
    checks = manifest.get("checks", {})
    for name in required:
        item = checks.get(name, {}) if isinstance(checks, dict) else {}
        if (
            not isinstance(item, dict)
            or item.get("status") != "passed"
            or not isinstance(item.get("evidence"), list)
            or not item["evidence"]
        ):
            blockers.append(name + "_pending")
            continue
        for reference in item["evidence"]:
            try:
                relative = reference["path"]
                path = (root / relative).resolve()
                if Path(relative).is_absolute() or not path.is_relative_to(root):
                    raise ValueError("Evidence outside root")
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != reference["sha256"]:
                    raise ValueError("Evidence changed")
                files[relative] = actual
            except (KeyError, TypeError, ValueError, OSError):
                blockers.append(name + "_invalid_evidence")
    return dict(
        stable_main_ready=not blockers,
        blockers=sorted(set(blockers)),
        source_revision=source.get("revision"),
        source_sha256=source.get("source_sha256"),
        evidence_sha256=files,
        evidence_meaning_independently_verified=False,
        provider_calls=0,
        merged=False,
        deployed=False,
    )


def main():
    from source import context

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--ci-report", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--write-template", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = context(args.checkout)
    if args.write_template:
        with args.write_template.open("x", encoding="utf-8") as stream:
            json.dump(template(source), stream, indent=2)

    def load(path):
        return json.loads(path.read_text("utf-8")) if path else {}

    report = check(
        source, load(args.manifest), load(args.ci_report), evidence_root=args.evidence_root
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(not report["stable_main_ready"])


if __name__ == "__main__":
    raise SystemExit(main())
