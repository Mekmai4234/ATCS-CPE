"""Browser + auth-enabled module-02 HTTP/worker with an isolated database.

python tests/identity_smoke.py --checkout
python tests/identity_smoke.py --ref origin/develop
Uses actual checkout source or a Git archive; never existing databases/real providers.
"""
import argparse
import hashlib
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
    parser.add_argument("--ref", default="origin/develop")
    parser.add_argument("--checkout", action="store_true", help="Use module-02 source from this actual checkout with an isolated DB")
    parser.add_argument("--local-evidence", action="store_true", help="Use actual05 fallback with synthetic providers, never live AI")
    parser.add_argument("--answers-ref", default="origin/feature/05_ai_answers_analysis")
    args = parser.parse_args()
    if args.local_evidence and not args.checkout:
        parser.error("Local evidence integration uses checkout backend plus an explicit05 source ref")
    web = Path(__file__).resolve().parents[1]
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=web, text=True).strip())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD" if args.checkout else args.ref], cwd=repo, text=True).strip()
    run = web / "runtime" / f"identity-check-{uuid4().hex[:10]}"
    run.mkdir(parents=True)
    root = run / "MiniProject"
    root.mkdir(exist_ok=True)
    if args.checkout:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        backend_source = web.parent / "02_api_backend" / "src"
    else:
        archive = subprocess.check_output(["git", "archive", "--format=zip", commit, "MiniProject/02_api_backend"], cwd=repo)
        with ZipFile(io.BytesIO(archive)) as bundle:
            if any(not (run / name).resolve().is_relative_to(run.resolve()) for name in bundle.namelist()):
                raise RuntimeError("Unsafe archive path")
            bundle.extractall(run)
        backend_source = root / "02_api_backend" / "src"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    api_url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PYTHONPATH=str(backend_source),
               MINIPROJECT_ROOT=str(root), DATABASE_URL=f"sqlite:///{(run / 'app.db').as_posix()}",
               CHROMA_PERSIST_DIR=str(run / "chroma"), ADAPTER_MODE="fixture", APP_ENV="test",
               AUTH_ENABLED="true", SESSION_COOKIE_SECURE="false", GOOGLE_CLIENT_ID="identity-fixture-client",
               API_HOST="127.0.0.1", API_PORT=str(port), WEB_ORIGIN="http://127.0.0.1:3004",
               AUTH_TRUSTED_ORIGINS='["http://127.0.0.1:3004"]',
               WORKER_POLL_SECONDS="0.05", JOB_RETRY_BASE_SECONDS="0.01", PYTHONDONTWRITEBYTECODE="1",
               WEB_IDENTITY_TEST="true", WEB_IDENTITY_API_URL=api_url,
               CHAT_REVIEW_ENABLED="true", CHAT_REVIEW_ADMIN_IDS='["fixture-admin"]')
    answers_commit = None
    if args.local_evidence:
        answers_commit = subprocess.check_output(["git", "rev-parse", args.answers_ref], cwd=repo, text=True).strip()
        archive = subprocess.check_output(["git", "archive", "--format=zip", answers_commit, "MiniProject/05_ai_answers_analysis"], cwd=repo)
        with ZipFile(io.BytesIO(archive)) as bundle:
            if any(not (run / name).resolve().is_relative_to(run.resolve()) for name in bundle.namelist()):
                raise RuntimeError("Unsafe answer source archive")
            bundle.extractall(run)
        env.update(
            PYTHONPATH=os.pathsep.join([str(backend_source), str(web / "tests"), str(root / "05_ai_answers_analysis" / "src")]),
            ADAPTER_MODE="custom", ADAPTER_FACTORY="local_evidence_fixture:create_adapters",
            WEB_LOCAL_EVIDENCE_TEST="true", GENERATION_PROVIDER="gemini",
            EMBEDDING_PROVIDER="fixture", EMBEDDING_MODEL="fixture-hash-v1", EMBEDDING_DIMENSIONS="64",
        )
    handles, processes = [], []
    outcome = {"backend_commit": commit, "source_mode": "actual_checkout" if args.checkout else "git_archive", "auth_enabled": True, "adapter_mode": "fixture", "external_verifier": "fixture", "real_google_tested": False, "paid_providers_called": False}
    outcome["frontend_files"] = {
        path.relative_to(web).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((web / "src").rglob("*")) if path.is_file()
    }
    if args.local_evidence:
        outcome.update(adapter_mode="actual05_with_synthetic_outage", answers_commit=answers_commit)
    try:
        for role, command in (
            ("api", [sys.executable, "-B", str(web / "tests" / "identity_server.py")]),
            ("worker", [sys.executable, "-B", "-m", "youtube_backend", "worker"]),
        ):
            if role == "worker":
                deadline = time.monotonic() + 30
                while True:
                    try:
                        with urlopen(api_url + "/health", timeout=1) as response:
                            if json.load(response).get("status") == "ok":
                                break
                    except Exception:
                        if time.monotonic() > deadline or processes[0].poll() is not None:
                            raise RuntimeError(f"Identity API did not start; see {run}")
                        time.sleep(0.2)
            log = (run / f"{role}.log").open("w", encoding="utf-8")
            handles.append(log)
            processes.append(subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT))
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js must be on PATH")
        grep = os.environ.get("WEB_IDENTITY_GREP") or ("actual05 local excerpts" if args.local_evidence else None)
        result = subprocess.run([node, str(web / "node_modules" / "@playwright" / "test" / "cli.js"), "test", "identity.spec.ts", "--workers=1", *(["--grep", grep] if grep else []), *(["--output", str(run / "browser-results")] if args.local_evidence else [])], cwd=web, env=env)
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
        print(f"Isolated identity evidence: {run}")


if __name__ == "__main__":
    raise SystemExit(main())
