"""Start full-team API/worker on fresh state, block outbound networking, then clean up."""

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

MODULE = Path(__file__).resolve().parents[1]


def main():
    project = f"yk07-startup-{uuid4().hex[:12]}"
    output = MODULE / "runtime" / project
    output.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, TEAM07_PORT=str(port), GEMINI_API_KEY="fixture07-no-provider-requests")
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        str(MODULE / "compose.yaml"),
        "-f",
        str(MODULE / "compose.startup-test.yaml"),
    ]
    report = dict(project=project, passed=False, live_provider_verified=False)

    def run(*args, required=True):
        result = subprocess.run(
            [*compose, *args],
            env=env,
            capture_output=True,
            timeout=180,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with (output / "docker.log").open("a", encoding="utf-8") as log:
            log.write(f"\nCOMMAND {args}\n{result.stdout}\n{result.stderr}\n")
        if required and result.returncode:
            raise RuntimeError(f"Docker operation failed: {args[0]}")
        return result

    started = time.monotonic()
    try:
        run("up", "-d", "--no-build", "--wait", "api", "worker")
        # The drill's internal network intentionally blocks host-published traffic.
        # Verify actual HTTP across service containers without enabling provider egress.
        health = json.loads(
            run(
                "exec",
                "-T",
                "worker",
                "python",
                "-c",
                "import urllib.request; "
                "print(urllib.request.urlopen('http://api:8000/health', "
                "timeout=10).read().decode())",
            ).stdout
        )
        required = {
            "ingest",
            "index",
            "delete",
            "evidence",
            "inventory",
            "answer",
            "analyze",
            "research",
            "artifact",
        }
        if any(health["capabilities"].get(key) != "available" for key in required):
            raise RuntimeError("Missing full-team capabilities")
        if health["live_provider_verified"]:
            raise RuntimeError("Startup must not claim verified live provider access")
        report.update(
            passed=True,
            health=health,
            services=json.loads(
                "[" + ",".join(run("ps", "--format", "json").stdout.splitlines()) + "]"
            ),
        )
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report["error"] = type(exc).__name__
    finally:
        try:
            run("logs", "--no-color", required=False)
        finally:
            cleaned = run("down", "--volumes", "--remove-orphans", required=False)
            report["cleanup_passed"] = cleaned.returncode == 0
        report["seconds"] = round(time.monotonic() - started, 3)
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Startup report: {output / 'report.json'}")
    return int(not report["passed"] or not report["cleanup_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
