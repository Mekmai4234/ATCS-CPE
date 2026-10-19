"""Build/test module 02 in Docker; use only a fresh, isolated Compose project/volume.

Run from MiniProject: uv run --project 02_api_backend python 02_api_backend/scripts/docker_smoke.py
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
VIDEO_A, VIDEO_B = "dQw4w9WgXcQ", "jNQXAC9IVRw"


class DockerCheck:
    expected_mode = "fixture"

    def __init__(self):
        self.project = f"yk02-check-{uuid4().hex[:10]}"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.environment = dict(os.environ, BACKEND_PORT=str(self.port))
        self.compose = [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(ROOT / "02_api_backend" / "compose.test.yaml"),
        ]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.directory = ROOT / "runtime" / self.project
        self.directory.mkdir(parents=True)
        self.log = self.directory / "docker.log"
        self.results = dict(
            project=self.project,
            started_at=datetime.now(UTC).isoformat(),
            adapter_mode="fixture",
            checks=[],
            passed=False,
        )

    def command(self, args, timeout=300, allow_failure=False):
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self.log.open("a", encoding="utf-8") as log:
            log.write(f"\n$ {' '.join(args)}\n{result.stdout}\n")
        if result.returncode and not allow_failure:
            raise RuntimeError(
                f"Command failed ({result.returncode}): {' '.join(args)}\n{result.stdout[-6000:]}"
            )
        return result

    def dc(self, *args, **kwargs):
        return self.command(self.compose + list(args), **kwargs)

    def check(self, name):
        self.results["checks"].append(name)
        print(f"PASS: {name}", flush=True)

    def request(self, method, path, body=None, key=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.status
            payload = json.loads(response.read())
            valid = expected if isinstance(expected, tuple) else (expected,)
            assert status in valid, (path, status, payload)
            assert response.headers["X-Adapter-Mode"] == self.expected_mode
            assert response.headers["X-Request-ID"]
            return payload, status

    def wait_job(self, job_id, expected="completed", stage=None):
        end = time.monotonic() + 45
        while time.monotonic() < end:
            data, _ = self.request("GET", f"/api/jobs/{job_id}")
            if data["state"] not in {"queued", "running"}:
                assert data["state"] == expected, data
                if stage:
                    assert data["stage"] == stage, data
                return data
            time.sleep(0.15)
        raise AssertionError(f"Job did not reach {expected}: {job_id}")

    def chat(self, question="Explain RAG", key=None):
        body = {"question": question, "scope": {"video_ids": [VIDEO_A]}}
        data, status = self.request("POST", "/api/chat", body, key=key, expected=(200, 202))
        return self.wait_job(data["job_id"])["result"] if status == 202 else data

    def run(self):
        try:
            self.results["docker"] = self.command(
                ["docker", "version", "--format", "{{.Server.Version}}"], 30
            ).stdout.strip()
            self.results["compose"] = self.command(
                ["docker", "compose", "version", "--short"], 30
            ).stdout.strip()
            self.dc("config", "--quiet", timeout=30)
            self.dc("--profile", "test", "build", "api", "tests", timeout=600)
            self.check("Runtime and test images build from uv.lock")
            suite = self.dc("run", "--rm", "--no-deps", "tests", timeout=180)
            match = re.search(r"(\d+) passed(?:.*? in ([\d.]+)s)?", suite.stdout)
            assert match, suite.stdout[-6000:]
            self.results["pytest"] = match.group(0)
            self.check(f"Linux container pytest: {match.group(0)}")
            self.dc("up", "-d", "--wait", "--wait-timeout", "90", "api", "worker", timeout=150)
            health, _ = self.request("GET", "/health")
            assert health["schema_revision"] == "0001" and health["mode"] == "fixture"
            identity = self.dc(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import json,os,platform; "
                "print(json.dumps({'uid':os.getuid(),'python':platform.python_version()}))",
                timeout=30,
            )
            self.results["container"] = json.loads(identity.stdout)
            assert self.results["container"]["uid"] == 10001
            self.check("Migration completes before healthy API; containers run as UID 10001")

            ids = [VIDEO_A, VIDEO_B, "NoCaption01", "Unavailable", "RetryOnce01", VIDEO_A]
            imported, _ = self.request(
                "POST",
                "/api/videos/import",
                {
                    "urls": [f"https://youtu.be/{video}" for video in ids]
                    + ["https://invalid.example/video"]
                },
                expected=202,
            )
            items = imported["jobs"]
            assert items[0]["job_id"] == items[5]["job_id"]
            assert items[5]["outcome"] == "existing" and items[6]["outcome"] == "rejected"
            for index in (0, 1, 4):
                job = self.wait_job(items[index]["job_id"], stage="ready")
                if index == 4:
                    assert job["attempt_count"] == 2
            self.wait_job(items[2]["job_id"], stage="no_transcript")
            unavailable = self.wait_job(items[3]["job_id"], expected="failed")
            assert unavailable["error_code"] == "video_unavailable"
            self.check(
                "HTTP imports: ready, duplicate, invalid URL, no captions, "
                "permanent failure and retry"
            )

            answer = self.chat(key="docker-chat-one")
            assert (
                answer["status"] == "answered"
                and answer["provider_metadata"]["provider"] == "fixture"
            )
            assert (
                answer["citations"][1]["url"] == f"https://www.youtube.com/watch?v={VIDEO_A}&t=12s"
            )
            replay = self.chat(key="docker-chat-one")
            assert replay["job_id"] == answer["job_id"]
            assert self.chat("weather tomorrow")["status"] == "insufficient_evidence"
            transcript, _ = self.request(
                "GET", f"/api/videos/{VIDEO_A}/transcript?limit=1&offset=1"
            )
            assert transcript["segments"][0]["start_seconds"] == 12
            self.check(
                "Chat citations, idempotent replay, insufficient evidence "
                "and timestamped transcript"
            )

            scope = {"video_ids": [VIDEO_A, VIDEO_B]}
            for kind in ("summary", "compare"):
                task, _ = self.request(
                    "POST", "/api/analysis", {"type": kind, "scope": scope}, expected=202
                )
                assert self.wait_job(task["job_id"])["result"]["coverage"]["complete"]
            research, _ = self.request(
                "POST", "/api/research", {"goal": "Learn RAG", "scope": scope}, expected=202
            )
            self.wait_job(research["job_id"])
            run, _ = self.request("GET", f"/api/research/{research['run_id']}")
            assert run["events"] and run["result"]["artifact_ids"]
            for kind in ("quiz", "flashcards", "study_plan"):
                task, _ = self.request(
                    "POST",
                    "/api/learning-artifacts",
                    {
                        "type": kind,
                        "scope": scope,
                        "days": 3,
                    },
                    expected=202,
                )
                result = self.wait_job(task["job_id"])["result"]
                artifact, _ = self.request(
                    "GET", f"/api/learning-artifacts/{result['artifact_ids'][0]}"
                )
                assert artifact["type"] == kind and artifact["sources_available"]
            self.check(
                "Background summary/comparison, research progress "
                "and all three learning artifact types"
            )

            # Make the queue deterministic, then replace BOTH containers with the same volume.
            self.dc("stop", "worker", timeout=30)
            cancelled, _ = self.request(
                "POST", "/api/research", {"goal": "Cancel me", "scope": scope}, expected=202
            )
            cancel, _ = self.request("POST", f"/api/research/{cancelled['run_id']}/cancel")
            assert cancel["state"] == "cancelled"
            queued, _ = self.request(
                "POST",
                "/api/videos/import",
                {"urls": ["https://youtu.be/AnotherId01"]},
                expected=202,
            )
            pending_id = queued["jobs"][0]["job_id"]
            pending, _ = self.request("GET", f"/api/jobs/{pending_id}")
            assert pending["state"] == "queued"
            self.dc(
                "up",
                "-d",
                "--force-recreate",
                "--wait",
                "--wait-timeout",
                "90",
                "api",
                "worker",
                timeout=180,
            )
            self.wait_job(pending_id, stage="ready")
            history, _ = self.request("GET", f"/api/conversations/{answer['conversation_id']}")
            assert history["total"] == 2
            self.check(
                "Queued cancellation and persisted jobs/history "
                "survive API/worker container recreation"
            )

            deleted, _ = self.request("DELETE", f"/api/videos/{VIDEO_A}", expected=202)
            self.wait_job(deleted["job_id"])
            self.request("GET", f"/api/videos/{VIDEO_A}/transcript", expected=404)
            history, _ = self.request("GET", f"/api/conversations/{answer['conversation_id']}")
            assert not history["messages"][1]["citations"][0]["source_available"]
            self.check(
                "Durable deletion removes transcripts and marks saved citation sources unavailable"
            )
            self.results["passed"] = True
        except BaseException as error:
            self.results["error"] = str(error)
            self.dc("logs", "--no-color", "--tail", "120", timeout=30, allow_failure=True)
            raise
        finally:
            # project is generated here and never accepts an existing user project name.
            cleaned = self.dc(
                "down", "--volumes", "--remove-orphans", timeout=60, allow_failure=True
            )
            self.results["cleanup_succeeded"] = cleaned.returncode == 0
            self.results["finished_at"] = datetime.now(UTC).isoformat()
            report = self.directory / "report.json"
            report.write_text(
                json.dumps(self.results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"Report: {report}\nLogs: {self.log}", flush=True)
            if cleaned.returncode:
                raise RuntimeError(f"Cleanup failed for isolated project {self.project}")


if __name__ == "__main__":
    try:
        DockerCheck().run()
    except Exception as error:
        print(f"Docker verification FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from None
