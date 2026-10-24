"""Serve the actual web image over local TLS; no live Google/provider requests."""

import json
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

MODULE = Path(__file__).resolve().parents[1]


def main():
    name = f"yk07-web-{uuid4().hex[:10]}"
    output = MODULE / "runtime" / name
    output.mkdir(parents=True)
    report = dict(passed=False, google_verified=False, public_https_verified=False)

    def docker(*args, check=True):
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=check,
        )

    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "PUBLIC_HOST=localhost",
            "-p",
            "127.0.0.1::443",
            "youtube-knowledge-team07-web:auth-check",
        )
        address = docker("port", name, "443/tcp").stdout.strip()
        port = address.rsplit(":", 1)[1]
        # Caddy's local CA is scoped to this disposable container, not installed on host.
        context = ssl._create_unverified_context()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
        )
        for attempt in range(30):
            try:
                with opener.open(f"https://localhost:{port}/", timeout=3) as response:
                    body = response.read().decode()
                    assert response.status == 200 and '<div id="root">' in body
                    assert response.headers["Cache-Control"] == "no-store"
                    assert response.headers["X-Content-Type-Options"] == "nosniff"
                break
            except (OSError, urllib.error.URLError):
                if attempt == 29:
                    raise
                time.sleep(1)
        with opener.open(f"https://localhost:{port}/admin", timeout=3) as response:
            assert response.status == 200 and response.read().decode() == body
        report.update(
            passed=True,
            local_tls_verified=True,
            spa_fallback_verified=True,
            image_id=docker("inspect", name, "--format", "{{.Image}}").stdout.strip(),
        )
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        (output / "container.log").write_text(
            docker("logs", name, check=False).stdout, encoding="utf-8"
        )
        report["cleanup_passed"] = docker("rm", "-fv", name, check=False).returncode == 0
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output / "report.json")
    return int(not report["passed"] or not report["cleanup_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
