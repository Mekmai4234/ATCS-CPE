"""Fail closed until backend identity and an explicit frontend integration attestation exist."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def check(settings, evidence=None):
    reasons = []
    if not getattr(settings, "auth_enabled", False):
        reasons.append("backend_auth_unavailable_or_disabled")
    if not getattr(settings, "google_client_id", ""):
        reasons.append("google_client_id_missing")
    if not getattr(settings, "session_cookie_secure", False):
        reasons.append("secure_session_cookie_required")
    origin = settings.web_origin
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        reasons.append("https_origin_required")
    trusted = getattr(settings, "auth_trusted_origins", [])
    if trusted and origin not in trusted:
        reasons.append("web_origin_not_trusted")
    # This attestation is an external acceptance artifact, not a runtime auth bypass.
    # It must describe the exact deployed commit/image and manual Google smoke.
    required = {
        "revision",
        "image_digest",
        "google_login",
        "logout_account_switch",
        "browser_backend_flow",
        "ownership_suites",
        "reviewed_by",
        "tested_at_utc",
    }
    if not isinstance(evidence, dict) or not required.issubset(evidence):
        reasons.append("integrated_release_evidence_missing")
    elif any(
        evidence[key] is not True
        for key in (
            "google_login",
            "logout_account_switch",
            "browser_backend_flow",
            "ownership_suites",
        )
    ) or any(
        not isinstance(evidence[key], str) or not evidence[key].strip()
        for key in ("revision", "image_digest", "reviewed_by", "tested_at_utc")
    ):
        reasons.append("integrated_release_evidence_incomplete")
    return dict(auth_release_ready=not reasons, blockers=reasons, secrets_printed=False)


def main():
    from preflight import resolve

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else None
        report = check(resolve(args.env_file), evidence)
    except Exception:
        parser.exit(2, "Auth release settings/evidence rejected (values redacted).\n")
    print(json.dumps(report, indent=2))
    return int(not report["auth_release_ready"])


if __name__ == "__main__":
    raise SystemExit(main())
