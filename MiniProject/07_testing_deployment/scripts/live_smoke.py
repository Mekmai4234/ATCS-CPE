"""Opt-in live URL -> captions -> index -> chat smoke against an explicitly selected local API."""

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
    parser.add_argument("--base-url", default="http://127.0.0.1:8007")
    parser.add_argument("--url", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    if not args.allow_live:
        parser.error(
            "--allow-live is required: imports persist data and Gemini calls can cost money"
        )
    base = args.base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Use an explicit local development API (http://127.0.0.1:PORT)")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    report = dict(mode="live", passed=False, semantic_quality_verified=False)
    started = time.monotonic()
    try:
        health = request(base, "/health")
        if health.get("synthetic_data") or health.get("integration_profile") != "live":
            raise ValueError("API must report the live integration profile without synthetic data")
        required = {"ingest", "index", "answer"}
        if any(health.get("capabilities", {}).get(name) != "available" for name in required):
            raise ValueError("API does not expose the required live capabilities")
        imported = request(base, "/api/videos/import", {"urls": [args.url]})["jobs"][0]
        job = poll(base, imported["job_id"], args.timeout)
        report["import_job"] = job["job_id"]
        if job.get("stage") != "ready":
            raise ValueError(f"Import ended at {job.get('stage')}; code={job.get('error_code')}")
        video_id = imported["video_id"]
        answer = request(
            base, "/api/chat", dict(question=args.question, scope=dict(video_ids=[video_id]))
        )
        answered = poll(base, answer["job_id"], args.timeout)
        report["answer_job"] = answered["job_id"]
        result = answered.get("result") or {}
        if answered["state"] != "completed" or result.get("status") != "answered":
            raise ValueError("Question did not produce a supported completed answer")
        citations = result.get("citations", [])
        if not citations or any(c["video_id"] != video_id for c in citations):
            raise ValueError("Citations missing or outside selected video")
        for citation in citations:
            url = urllib.parse.urlsplit(citation["url"])
            query = urllib.parse.parse_qs(url.query)
            if (
                url.scheme != "https"
                or url.hostname != "www.youtube.com"
                or query.get("v") != [video_id]
                or query.get("t") != [str(int(citation["start_seconds"])) + "s"]
                or not 0 <= citation["start_seconds"] < citation["end_seconds"]
            ):
                raise ValueError("Citation timestamp URL or interval is invalid")
        report.update(
            passed=True,
            result=result,
            review_required="Compare every claim and cited interval with the actual video",
        )
    except (ValueError, KeyError, TimeoutError, urllib.error.URLError):
        # Avoid logging raw upstream HTTP errors or request bodies.
        report["failure"] = (
            "Live acceptance failed; inspect saved job IDs and provider status locally"
        )
    report["seconds"] = round(time.monotonic() - started, 3)
    output = MODULE / "runtime" / f"live-{time.time_ns()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
