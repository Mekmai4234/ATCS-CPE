"""Legacy smoke is blocked until project review and enforceable per-smoke budgets exist."""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]


def request(base, path, body=None):
    req = urllib.request.Request(
        base + path,
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def poll(base, job_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = request(base, f"/api/jobs/{urllib.parse.quote(job_id, safe='')}")
        if job["state"] in {"completed", "failed", "cancelled", "partial"}:
            return job
        time.sleep(0.5)
    raise TimeoutError("Job polling deadline exceeded; server job may still need cancellation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--free-tier-evidence", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8007")
    parser.add_argument("--url", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    if not args.allow_live:
        parser.error(
            "--allow-live and reviewed Free Tier evidence are required; imports persist data"
        )
    base = args.base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Use an explicit local development API (http://127.0.0.1:PORT)")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    # Legacy endpoint can fan out into an unbounded provider call graph and has no
    # execution-bound smoke budget API. Do not turn an attestation into permission
    # to call it. Re-enable only after 02 exposes enforceable per-smoke reservations.
    try:
        from free_tier import require
        from preflight import resolve

        require(resolve(args.env_file), args.free_tier_evidence)
    except Exception:
        parser.exit(2, "Live smoke blocked: Free Tier evidence not accepted (values redacted).\n")
    parser.exit(2, "Live smoke blocked: bounded end-to-end broker smoke endpoint not integrated.\n")


if __name__ == "__main__":
    raise SystemExit(main())
