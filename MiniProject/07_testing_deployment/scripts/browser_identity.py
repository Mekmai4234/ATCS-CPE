"""Exercise 01's real HTTP adapter against the pinned 02 API/worker, external GIS doubled."""

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from check import clean_environment, run_command
from source import context

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parent


def main():
    web = ROOT / "01_web_app"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", action="store_true")
    args = parser.parse_args()
    provenance = context(args.checkout)
    output = MODULE / "runtime" / f"browser-identity-{uuid4().hex[:10]}"
    output.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = clean_environment()
    env.update(
        DATABASE_URL=f"sqlite:///{(output / 'app.db').as_posix()}",
        CHROMA_PERSIST_DIR=str(output / "chroma"),
        APP_ENV="test",
        ADAPTER_MODE="fixture",
        AUTH_ENABLED="true",
        SESSION_COOKIE_SECURE="false",
        GOOGLE_CLIENT_ID="identity-fixture-client",
        API_HOST="127.0.0.1",
        API_PORT=str(port),
        WEB_ORIGIN="http://127.0.0.1:3004",
        AUTH_TRUSTED_ORIGINS='["http://127.0.0.1:3004"]',
        WORKER_POLL_SECONDS="0.05",
        JOB_RETRY_BASE_SECONDS="0.01",
        WEB_IDENTITY_TEST="true",
        WEB_IDENTITY_API_URL=f"http://127.0.0.1:{port}",
    )
    processes, handles = [], []
    report = dict(
        passed=False,
        real_google_verified=False,
        production_tls_verified=False,
        backend_adapter="fixture",
        frontend_adapter="HttpSessionPort",
        api_routes_mocked=False,
        paid_providers_called=False,
        source=provenance,
    )
    if not (web / "tests/identity_server.py").is_file():
        report.update(
            passed=None,
            status="blocked",
            cleanup_passed=True,
            blockers=["actual_frontend_has_no_identity_harness"],
        )
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(output / "report.json")
        return 2
    try:
        for role, args in (
            ("api", [sys.executable, str(web / "tests/identity_server.py")]),
            ("worker", [sys.executable, "-m", "youtube_backend", "worker"]),
        ):
            if role == "worker":
                deadline = time.monotonic() + 40
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                while True:
                    try:
                        with opener.open(env["WEB_IDENTITY_API_URL"] + "/health", timeout=1) as r:
                            assert json.load(r)["authentication_required"]
                        break
                    except OSError:
                        if time.monotonic() > deadline or processes[0].poll() is not None:
                            raise RuntimeError("Identity API startup failed") from None
                        time.sleep(0.2)
            handle = (output / f"{role}.log").open("wb")
            handles.append(handle)
            processes.append(
                subprocess.Popen(args, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
            )
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node is required")
        code, log = run_command(
            [
                node,
                str(web / "node_modules/@playwright/test/cli.js"),
                "test",
                "--config",
                str(MODULE / "playwright.identity.config.ts"),
                "identity.spec.ts",
                "--workers=1",
            ],
            env,
            420,
        )
        (output / "browser.log").write_bytes(log)
        report.update(passed=code == 0, browser_exit_code=code)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        for handle in handles:
            handle.close()
        report["cleanup_passed"] = all(p.poll() is not None for p in processes)
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output / "report.json")
    return int(not report["passed"] or not report["cleanup_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
