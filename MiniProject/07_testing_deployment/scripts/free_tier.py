"""Offline release evidence gate. Never contacts Google or certifies billing itself."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from source import capture

CHECKS = (
    "contract_v2_v1_history",
    "migration_paired_restore",
    "privacy_revoke_finalize",
    "shared_broker_all_requests",
    "quota_races_retry_cache",
    "browser_media_pause_accessibility",
    "visual_only_no_fake_transcript",
    "seven_clip_review",
    "server_capacity_cleanup",
)


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Aware timestamp required")
    return result.astimezone(UTC)


def positive(value):
    return type(value) is int and 0 < value <= 1_000_000_000


def check(settings, evidence=None, *, source=None, now=None):
    """Check a reviewed artifact against exact source/config, with no key in output.

    Review booleans are operator assertions, not executable enforcement. Backend's
    execution-bound broker must enforce each request and token reservation separately.
    """
    reasons = []
    now = now or datetime.now(UTC)
    evidence = evidence if isinstance(evidence, dict) else {}
    if evidence.get("schema") != 1 or evidence.get("tier") != "free":
        reasons.append("operator_free_tier_attestation_required")
    for key in ("ai_studio_checked", "key_project_match", "model_access_checked"):
        if evidence.get(key) is not True:
            reasons.append(key + "_required")
    try:
        checked, expires = map(timestamp, (evidence["checked_at"], evidence["expires_at"]))
        if not checked <= now < expires or not 0 < (expires - checked).total_seconds() <= 86400:
            raise ValueError("Expired/future evidence")
        if not all(
            isinstance(evidence.get(key), str) and re.fullmatch(r"[\w .:/-]{1,160}", evidence[key])
            for key in ("project_ref", "reviewed_by", "evidence_ref")
        ):
            raise ValueError("Review reference missing")
    except (KeyError, TypeError, ValueError):
        reasons.append("fresh_dated_operator_review_required")
    key = settings.gemini_api_key.get_secret_value()
    if not key or evidence.get("key_sha256") != hashlib.sha256(key.encode()).hexdigest():
        reasons.append("reviewed_key_binding_required")
    if getattr(settings, "embedding_provider", None) != "gemini":
        reasons.append("gemini_only_provider_required")
    models = evidence.get("models", {})
    for role, model, endpoint in (
        ("chat", settings.llm_model, "generateContent"),
        ("vision", settings.llm_model, "generateContent"),
        ("embedding", settings.embedding_model, "embedContent"),
        ("agent", settings.llm_model, "generateContent"),
    ):
        grant = models.get(role, {}) if isinstance(models, dict) else {}
        if (
            not isinstance(grant, dict)
            or grant.get("requested_model") != model
            or grant.get("endpoint") != endpoint
            or not isinstance(grant.get("returned_models"), list)
            or not grant["returned_models"]
            or any(not isinstance(m, str) or not m for m in grant["returned_models"])
            or not all(positive(grant.get(k)) for k in ("rpm", "tpm", "rpd"))
        ):
            reasons.append(role + "_model_limits_required")
    budget = evidence.get("smoke_budget", {})
    if (
        not isinstance(budget, dict)
        or not all(positive(budget.get(k)) for k in ("max_requests", "max_input_tokens"))
        or budget["max_requests"] > 3
        or budget["max_input_tokens"] > 4096
    ):
        reasons.append("bounded_smoke_budget_required")
    try:
        source = source or capture()
        if (
            source["mode"] != "checkout"
            or source["dirty"] is not False
            or evidence.get("revision") != source["revision"]
            or evidence.get("source_sha256") != source["source_sha256"]
        ):
            raise ValueError("Wrong source")
    except (KeyError, OSError, ValueError):
        reasons.append("clean_exact_checkout_evidence_required")
    checks = evidence.get("checks", {})
    for name in CHECKS:
        if not isinstance(checks, dict) or checks.get(name) is not True:
            reasons.append(name + "_not_accepted")
    # The backend gate is independently required. Catalog lookup and a 07 JSON
    # artifact cannot supply a missing production quota implementation.
    try:
        from youtube_backend.quota import FreePolicy

        path = Path(settings.gemini_free_policy_file)
        if not path.is_absolute():
            from youtube_backend.config import PROJECT_ROOT

            path = PROJECT_ROOT / path
        policy = FreePolicy.model_validate_json(path.read_text(encoding="utf-8"))
        if (
            policy.project_ref != evidence.get("project_ref")
            or policy.key_sha256 != evidence.get("key_sha256")
            or not policy.verified_at <= now < policy.expires_at
        ):
            raise ValueError("Runtime policy differs")
        for role, grant in models.items():
            match = next(
                (
                    m
                    for m in policy.models
                    if m.model == grant["requested_model"] and role in m.roles
                ),
                None,
            )
            if match is None or grant["endpoint"] not in match.endpoints:
                raise ValueError("Runtime model/role differs")
            pool = policy.pools[match.bucket]
            if set(match.returned_models) != set(grant["returned_models"]) or any(
                getattr(pool, k) != grant[k] for k in ("rpm", "tpm", "rpd")
            ):
                raise ValueError("Runtime quota/model alias differs")
    except (ImportError, AttributeError, OSError, TypeError, KeyError, ValueError):
        reasons.append("matching_backend_broker_policy_required")
    return dict(
        free_tier_release_ready=not reasons,
        blockers=reasons,
        billing_verified_by_tool=False,
        provider_request_made=False,
        secret_values_printed=False,
    )


def require(settings, path):
    evidence = json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    result = check(settings, evidence)
    if not result["free_tier_release_ready"]:
        raise ValueError("Free Tier release evidence is not accepted")
    return result


def main():
    from preflight import resolve

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else None
        result = check(resolve(args.env_file), evidence)
    except Exception:
        parser.exit(2, "Free Tier settings/evidence rejected (values redacted).\n")
    print(json.dumps(result, indent=2))
    return 0 if result["free_tier_release_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
