"""Offline full-image suite and separate real-factory API/worker startup smoke.

The runtime smoke uses an invalid test key and an internal network (no egress).
It never asks YouTube/Gemini to process a video. Full data-flow doubles are only
in pytest, not the runtime image. Cleans only its own generated Compose project.
"""

import json
import os
import re
import sys
from datetime import UTC, datetime

from docker_smoke import ROOT, VIDEO_A, DockerCheck

CLIENT = """
import json, sys, urllib.request, urllib.error
method, path, body = sys.argv[1:]
request = urllib.request.Request(
    'http://127.0.0.1:8000' + path,
    data=None if body == 'null' else body.encode(),
    headers={'Content-Type': 'application/json'}, method=method)
try:
    response = urllib.request.urlopen(request, timeout=15)
except urllib.error.HTTPError as error:
    response = error
with response:
    print(json.dumps({'status': response.status, 'body': json.loads(response.read()),
                      'mode': response.headers.get('X-Adapter-Mode'),
                      'request_id': response.headers.get('X-Request-ID')}))
"""


class FullCheck(DockerCheck):
    expected_mode = "custom"

    def request(self, method, path, body=None, key=None, expected=200):
        # Internal networks need no Docker Desktop host-port forwarding for this check.
        result = self.dc(
            "exec", "-T", "api", "python", "-c", CLIENT, method, path, json.dumps(body), timeout=30
        )
        response = json.loads(result.stdout)
        valid = expected if isinstance(expected, tuple) else (expected,)
        assert response["status"] in valid, response
        assert response["mode"] == self.expected_mode and response["request_id"]
        return response["body"], response["status"]

    def __init__(self):
        super().__init__()
        override = self.directory / "internal.yaml"
        override.write_text("networks:\n  default:\n    internal: true\n", encoding="utf-8")
        self.compose = [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(ROOT / "02_api_backend" / "compose.full.yaml"),
            "-f",
            str(override),
        ]
        self.environment = dict(
            os.environ,
            BACKEND_FULL_PORT=str(self.port),
            GEMINI_API_KEY="test-only-invalid-key",
            LLM_MODEL="gemini-3.5-flash",
        )
        self.results.update(
            adapter_mode="custom",
            profile="live",
            external_provider_calls=False,
            verification="offline doubles plus real-factory startup only",
        )

    def run(self):
        try:
            self.dc("config", "--quiet", timeout=30)
            self.dc("--profile", "test", "build", "api", "tests", timeout=900)
            self.check("Locked full 02/03/04/05/06 runtime and test images built")
            suite = self.dc("run", "--rm", "--no-deps", "tests", timeout=300)
            result = re.search(r"\d+ passed.*? in [\d.]+s", suite.stdout)
            assert result, suite.stdout[-5000:]
            self.results["pytest"] = result.group(0)
            self.check("Network-disabled Linux suite: " + result.group(0))
            self.dc("up", "-d", "--wait", "--wait-timeout", "90", "api", "worker", timeout=150)
            health, _ = self.request("GET", "/health")
            assert set(health["capabilities"].values()) == {"available"}
            assert health["full_pair_preflight"] and not health["live_provider_verified"]
            identity = self.dc(
                "exec", "-T", "api", "python", "-c", "import os; print(os.getuid())", timeout=30
            )
            assert identity.stdout.strip() == "10001"
            self.dc("run", "--rm", "--no-deps", "maintenance", timeout=30)
            self.check("Shared pair verified; real full-factory API/worker start as non-root")
            mismatch = self.dc(
                "run",
                "--rm",
                "--no-deps",
                "-e",
                "CHROMA_PERSIST_DIR=/app/runtime/wrong",
                "maintenance",
                timeout=30,
                allow_failure=True,
            )
            assert mismatch.returncode != 0
            self.check("Wrong Chroma directory is rejected before maintenance")
            self.dc("stop", "worker", timeout=30)
            imported, _ = self.request(
                "POST",
                "/api/videos/import",
                {"urls": [f"https://youtu.be/{VIDEO_A}"]},
                expected=202,
            )
            job_id = imported["jobs"][0]["job_id"]
            cancel, _ = self.request("POST", f"/api/jobs/{job_id}/cancel")
            assert cancel["state"] == "cancelled"
            self.dc(
                "up",
                "-d",
                "--force-recreate",
                "--wait",
                "--wait-timeout",
                "90",
                "api",
                "worker",
                timeout=150,
            )
            persisted, _ = self.request("GET", f"/api/jobs/{job_id}")
            assert persisted["state"] == "cancelled"
            self.check("HTTP import/cancel and pair/job state survive API/worker recreation")
            self.results["passed"] = True
        except BaseException:
            self.dc("logs", "--no-color", "--tail", "80", timeout=30, allow_failure=True)
            raise
        finally:
            cleanup = self.dc(
                "down", "--volumes", "--remove-orphans", timeout=60, allow_failure=True
            )
            self.results["cleanup_succeeded"] = cleanup.returncode == 0
            self.results["finished_at"] = datetime.now(UTC).isoformat()
            report = self.directory / "report.json"
            report.write_text(json.dumps(self.results, indent=2), encoding="utf-8")
            print(f"Report: {report}\nLogs: {self.log}", flush=True)
            if cleanup.returncode:
                raise RuntimeError("Could not clean the generated full-system test project")


if __name__ == "__main__":
    try:
        FullCheck().run()
    except Exception as exc:
        print(f"Full Docker verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
