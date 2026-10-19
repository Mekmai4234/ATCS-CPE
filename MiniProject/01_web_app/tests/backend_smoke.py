"""Run the browser against module 02 from a local Git ref, without checking it out.

Usage from 01_web_app, using Python with module 02 dependencies installed:
    python tests/backend_smoke.py --ref develop
All extracted sources, logs and the fresh fixture DB stay in ignored runtime/.
No credentials, external AI calls, Git mutations or existing databases are used.
"""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", default="develop")
    args = parser.parse_args()
    web = Path(__file__).resolve().parents[1]
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=web, text=True).strip())
    commit = subprocess.check_output(["git", "rev-parse", args.ref], cwd=repo, text=True).strip()
    archive = subprocess.check_output(["git", "archive", "--format=zip", commit, "MiniProject/02_api_backend"], cwd=repo)
    run = web / "runtime" / f"backend-check-{uuid4().hex[:10]}"
    run.mkdir(parents=True)
    with ZipFile(io.BytesIO(archive)) as bundle:
        for name in bundle.namelist():
            if not (run / name).resolve().is_relative_to(run.resolve()):
                raise RuntimeError("Unsafe archive path")
        bundle.extractall(run)
    root = run / "MiniProject"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, PYTHONPATH=str(root / "02_api_backend" / "src"),
               MINIPROJECT_ROOT=str(root), DATABASE_URL=f"sqlite:///{(run / 'app.db').as_posix()}",
               ADAPTER_MODE="fixture", APP_ENV="test", API_HOST="127.0.0.1", API_PORT=str(port),
               WEB_ORIGIN="http://127.0.0.1:3002", WORKER_POLL_SECONDS="0.05",
               JOB_RETRY_BASE_SECONDS="0.01", PYTHONDONTWRITEBYTECODE="1",
               WEB_BACKEND_TEST="true", WEB_TEST_API_URL=f"http://127.0.0.1:{port}")
    command = [sys.executable, "-B", "-m", "youtube_backend"]
    processes = []
    handles = []
    outcome = {"backend_commit": commit, "adapter_mode": "fixture", "paid_providers_called": False}
    try:
        subprocess.run([*command, "db", "upgrade", "head"], cwd=root, env=env, check=True)
        for role in ("api", "worker"):
            log = (run / f"{role}.log").open("w", encoding="utf-8")
            handles.append(log)
            processes.append(subprocess.Popen([*command, role], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + 20
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    if json.load(response).get("status") == "ok":
                        break
            except Exception:
                if time.monotonic() >= deadline or any(p.poll() is not None for p in processes):
                    raise RuntimeError(f"API did not start; inspect {run}")
                time.sleep(0.2)
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js must be on PATH")
        result = subprocess.run([node, str(web / "node_modules" / "@playwright" / "test" / "cli.js"), "test", "backend.spec.ts", "--workers=1"], cwd=web, env=env)
        outcome["browser_exit_code"] = result.returncode
        return result.returncode
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()
        (run / "report.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
        print(f"Isolated test artifacts: {run}")


if __name__ == "__main__":
    raise SystemExit(main())
