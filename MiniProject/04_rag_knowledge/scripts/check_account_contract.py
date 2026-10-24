"""Verify actual locked dependencies in a disposable candidate, never a PYTHONPATH swap.

Invoke with uv run --no-project python scripts/check_account_contract.py before
02 merges. This script never repairs a lock or edits another module's checkout.
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from uuid import uuid4

BASE = "1814bf3622eb62f0963da4f682ea31661728907c"
INGESTION = "1814bf3622eb62f0963da4f682ea31661728907c"
AGENT = "1814bf3622eb62f0963da4f682ea31661728907c"


def git(repo, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=repo)


def export(repo, ref, path, target):
    commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    archive = git(repo, "archive", "--format=zip", commit, "--", path)
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        for item in package.infolist():
            if item.is_dir():
                continue
            destination = (target / item.filename).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("Unsafe archive path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(package.read(item))
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-ref", required=True)
    parser.add_argument("--base-ref", default=BASE)
    parser.add_argument("--ingestion-ref", default=INGESTION)
    parser.add_argument("--agent-ref", default=AGENT)
    parser.add_argument(
        "--prepare-only", action="store_true", help="Export only; never repair locks"
    )
    parser.add_argument(
        "--full-integration", action="store_true", help="Also test the native 02 full factory"
    )
    parser.add_argument("--docker-image", help="Build AND test this tag from the same candidate")
    args = parser.parse_args()
    module = Path(__file__).resolve().parents[1]
    repo = Path(git(module, "rev-parse", "--show-toplevel").decode().strip())
    output = module / "runtime" / f"locked-candidate-{uuid4().hex[:10]}"
    output.mkdir(parents=True)
    candidate = output / "MiniProject"
    report = {"refs": {}, "steps": {}, "verified": False, "whole_system_verified": False}
    print(f"Candidate: {candidate}", flush=True)
    try:
        for path, ref in (
            (".env.example", args.base_ref),
            ("02_api_backend", args.backend_ref),
            ("03_video_ingestion", args.ingestion_ref),
            ("05_ai_answers_analysis", args.base_ref),
            ("06_research_learning_agent", args.agent_ref),
        ):
            report["refs"][path] = export(repo, ref, f"MiniProject/{path}", output)
        prefix = "MiniProject/04_rag_knowledge/"
        files = git(
            repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", prefix
        )
        report["04_files_sha256"] = {}
        for name in filter(None, files.decode().split("\0")):
            source = repo / name
            if not name.startswith(prefix) or not source.resolve().is_relative_to(module):
                raise ValueError("Unexpected module path")
            if source.name == ".env" or not source.is_file():
                continue
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            report["04_files_sha256"][name] = hashlib.sha256(source.read_bytes()).hexdigest()
        if args.prepare_only:
            report["prepared_only"] = True
            return 0

        environment = dict(
            os.environ,
            MINIPROJECT_ROOT=str(candidate),
            APP_ENV="test",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            RUN_LIVE_EMBEDDING_TESTS="0",
            PYTHONDONTWRITEBYTECODE="1",
            UV_NO_PROGRESS="1",
        )
        for name in ("PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
            environment.pop(name, None)
        # Keep Windows dependency paths below the import loader's path limit. The
        # environment is still fresh and belongs only to this disposable candidate.
        environment["UV_PROJECT_ENVIRONMENT"] = str(output / "venv04")

        def run(label, arguments, *, cwd=candidate, timeout=1800):
            with (output / f"{label}.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    arguments,
                    cwd=cwd,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            report["steps"][label] = result.returncode
            print(f"{label}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
            if result.returncode:
                raise RuntimeError(f"{label} failed; inspect {output / (label + '.log')}")

        run("04-lock", ["uv", "lock", "--project", "04_rag_knowledge", "--check", "--offline"])
        run("04-sync", ["uv", "sync", "--project", "04_rag_knowledge", "--locked"])
        probe = (
            "from importlib.metadata import requires; from pathlib import Path; "
            "import youtube_backend; import chromadb; "
            "p=Path(youtube_backend.__file__).resolve(); "
            "assert p.is_relative_to(Path('../02_api_backend/src').resolve()); "
            "r=requires('youtube-knowledge-backend'); "
            "assert any(x.startswith('google-auth') for x in r); "
            "assert any(x.startswith('requests') for x in r); "
            "print(p); print(r)"
        )
        run(
            "installed-backend",
            ["uv", "run", "--locked", "--offline", "python", "-c", probe],
            cwd=candidate / "04_rag_knowledge",
        )
        run(
            "04-tests",
            [
                "uv",
                "run",
                "--locked",
                "--offline",
                "pytest",
                "tests",
                "-q",
                "-W",
                "error",
                f"--junitxml={output / '04-tests.xml'}",
            ],
            cwd=candidate / "04_rag_knowledge",
        )
        if args.full_integration:
            environment["UV_PROJECT_ENVIRONMENT"] = str(output / "venv-full")
            full = "02_api_backend/full"
            run("full-lock", ["uv", "lock", "--project", full, "--check", "--offline"])
            run("full-sync", ["uv", "sync", "--project", full, "--locked"])
            run(
                "native-full-tests",
                [
                    "uv",
                    "run",
                    "--project",
                    full,
                    "--locked",
                    "--offline",
                    "pytest",
                    "02_api_backend/tests",
                    "02_api_backend/integration/tests",
                    "02_api_backend/full/tests",
                    "-q",
                    "-W",
                    "error",
                    f"--junitxml={output / 'native-full-tests.xml'}",
                ],
            )
        if args.docker_image:
            run(
                "docker-build",
                [
                    "docker",
                    "build",
                    "-f",
                    "04_rag_knowledge/Dockerfile",
                    "-t",
                    args.docker_image,
                    ".",
                ],
            )
            run(
                "docker-04-tests",
                [
                    "docker",
                    "run",
                    "--rm",
                    "--init",
                    "--network",
                    "none",
                    "-e",
                    "GEMINI_API_KEY=",
                    "-e",
                    "RUN_LIVE_EMBEDDING_TESTS=0",
                    args.docker_image,
                    "pytest",
                    "tests",
                    "-q",
                    "-W",
                    "error",
                    "-o",
                    "cache_dir=/tmp/pytest-cache",
                ],
            )
        report["verified"] = True
        return 0
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
