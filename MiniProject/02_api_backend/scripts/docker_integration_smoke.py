"""02-owned real API/worker/Chroma integration. Models and captions are offline doubles."""

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime

from docker_smoke import ROOT, VIDEO_A, VIDEO_B, DockerCheck


class IntegrationCheck(DockerCheck):
    expected_mode = "custom"

    def __init__(self, keep=False):
        super().__init__()
        self.keep = keep
        self.compose = [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(ROOT / "02_api_backend" / "compose.integration.yaml"),
        ]
        self.environment = dict(
            os.environ,
            APP_ENV="test",
            AUTH_ENABLED="false",
            BACKEND_INTEGRATION_PORT=str(self.port),
            BACKEND_INTEGRATION_PROFILE="offline",
            GEMINI_API_KEY="",
            RUN_LIVE_EMBEDDING_TESTS="0",
        )
        self.results.update(adapter_mode="custom", integration_profile="offline")

    def run(self):
        try:
            self.dc("config", "--quiet", timeout=30)
            self.dc("--profile", "test", "build", "api", "tests", timeout=600)
            self.check("Build 02-owned integration image with unchanged 04/06 packages")
            suite = self.dc("run", "--rm", "--no-deps", "tests", timeout=240)
            match = re.search(r"\d+ passed.*? in [\d.]+s", suite.stdout)
            assert match, suite.stdout[-5000:]
            self.results["pytest"] = match.group(0)
            self.check("Linux offline suite: " + match.group(0))
            self.dc("run", "--rm", "--no-deps", "migrate", timeout=60)
            self.dc("run", "--rm", "--no-deps", "seed", timeout=90)
            self.dc("up", "-d", "--wait", "--wait-timeout", "90", "api", "worker", timeout=150)
            health, _ = self.request("GET", "/health")
            assert health["synthetic_data"] and health["integration_profile"] == "offline"
            assert health["capabilities"]["research"] == "available"
            assert health["capabilities"]["ingest"] == "unavailable"
            self.request(
                "POST",
                "/api/videos/import",
                {"urls": [f"https://youtu.be/{VIDEO_A}"]},
                expected=503,
            )
            self.request(
                "POST",
                "/api/chat",
                {"question": "RAG", "scope": {"video_ids": [VIDEO_A]}},
                expected=503,
            )
            self.check(
                "Explicit initialization, offline-only seed, health and missing 03/05 capabilities"
            )
            scope = {"video_ids": [VIDEO_A, VIDEO_B]}
            artifact_ids = []
            for kind in ("quiz", "flashcards", "study_plan"):
                accepted, _ = self.request(
                    "POST",
                    "/api/learning-artifacts",
                    {
                        "type": kind,
                        "scope": scope,
                        "days": 3,
                    },
                    key=f"docker-{kind}",
                    expected=202,
                )
                job = self.wait_job(accepted["job_id"])
                assert job["result"]["provider_metadata"]["provider"] == "fixture"
                artifact_id = job["result"]["artifact_ids"][0]
                artifact_ids.append(artifact_id)
                artifact, _ = self.request("GET", f"/api/learning-artifacts/{artifact_id}")
                assert artifact["sources_available"] and artifact["citations"]
            body = {"goal": "Study the RAG evidence", "scope": scope, "days": 3}
            accepted, _ = self.request(
                "POST", "/api/research", body, key="docker-research", expected=202
            )
            job_id = accepted["job_id"]
            job = self.wait_job(job_id)
            assert job["result"]["coverage"]["complete"]
            run, _ = self.request("GET", f"/api/research/{job_id}")
            assert {event["tool_name"] for event in run["events"]} >= {
                "read_video_chunks",
                "create_learning_artifact",
            }
            replay, _ = self.request(
                "POST", "/api/research", body, key="docker-research", expected=202
            )
            assert replay["job_id"] == job_id
            self.check(
                "Real 04 retrieval and 06 controller through API/worker, "
                "all artifacts and idempotency"
            )
            self.dc("stop", "worker", timeout=30)
            pending, _ = self.request(
                "POST",
                "/api/learning-artifacts",
                {
                    "type": "quiz",
                    "scope": scope,
                },
                expected=202,
            )
            cancelled, _ = self.request("POST", "/api/research", body, expected=202)
            state, _ = self.request("POST", f"/api/research/{cancelled['job_id']}/cancel")
            assert state["state"] == "cancelled"
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
            self.wait_job(pending["job_id"])
            persisted, _ = self.request("GET", f"/api/research/{job_id}")
            assert persisted["result"] == job["result"]
            for artifact_id in artifact_ids:
                artifact, _ = self.request("GET", f"/api/learning-artifacts/{artifact_id}")
                assert artifact["sources_available"]
            self.check(
                "Container recreation preserves SQLite, real Chroma, pending jobs and saved results"
            )
            deleted, _ = self.request("DELETE", f"/api/videos/{VIDEO_A}", expected=202)
            self.wait_job(deleted["job_id"])
            self.request("GET", f"/api/videos/{VIDEO_A}/transcript", expected=404)
            artifact, _ = self.request("GET", f"/api/learning-artifacts/{artifact_ids[0]}")
            assert not artifact["sources_available"]
            # The other source remains usable after one video's vectors are deleted.
            task, _ = self.request(
                "POST",
                "/api/learning-artifacts",
                {
                    "type": "quiz",
                    "scope": {"video_ids": [VIDEO_B]},
                },
                expected=202,
            )
            self.wait_job(task["job_id"])
            self.check(
                "Real vector deletion, historical availability and unaffected source generation"
            )
            self.results["passed"] = True
        except BaseException as error:
            self.results["error"] = str(error)
            self.dc("logs", "--no-color", "--tail", "100", allow_failure=True, timeout=30)
            raise
        finally:
            retain = self.keep and self.results["passed"]
            self.results["resources_retained"] = retain
            if not retain:
                cleaned = self.dc(
                    "down", "--volumes", "--remove-orphans", timeout=60, allow_failure=True
                )
                self.results["cleanup_succeeded"] = cleaned.returncode == 0
            self.results["finished_at"] = datetime.now(UTC).isoformat()
            self.results["url"] = self.base_url
            report = self.directory / "report.json"
            report.write_text(json.dumps(self.results, indent=2), encoding="utf-8")
            print(f"Report: {report}", flush=True)
            if retain:
                print(f"Containers left running: {self.project}; {self.base_url}/docs", flush=True)
            elif not self.results["cleanup_succeeded"]:
                raise RuntimeError(f"Cleanup failed for {self.project}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep", action="store_true", help="Keep successful demo containers/volume for inspection"
    )
    options = parser.parse_args()
    try:
        IntegrationCheck(options.keep).run()
    except Exception as error:
        print(f"Docker integration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
