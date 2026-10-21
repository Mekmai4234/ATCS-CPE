"""Verify pinned auth PRs in a disposable copy; never merge or edit consumer files.

Only committed inputs and current non-ignored module-02 files are exported. Private
dotenv files, databases and virtualenvs are not copied. Reports/consumer lock patches
remain in ignored module-02 runtime storage for their owners to review.
"""

import argparse
import difflib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
REFS = {
    "03_video_ingestion": "4b051318b5816c6bc247a038f48eff6d21b7e741",
    "04_rag_knowledge": "d4aa52d137b44f9217923bd18afc77b6a00881ef",
    "06_research_learning_agent": "84fb1b6e40f3dd685df4c8d300ba058612de6c09",
    "07_testing_deployment": "04c835211ce44f3e914348b302324c351479f41b",
}
PROJECTS = (
    "02_api_backend",
    "02_api_backend/integration",
    "02_api_backend/full",
    "03_video_ingestion",
    "04_rag_knowledge",
    "05_ai_answers_analysis",
    "06_research_learning_agent",
    "06_research_learning_agent/acceptance",
    "07_testing_deployment",
)


def command(args, cwd=ROOT, env=None):
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        check=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


def export(repo, ref, path, destination):
    # Resolve refs first and use argument arrays; refs are never shell commands.
    commit = command(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], repo).decode().strip()
    data = command(["git", "archive", commit, "--", path], repo)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(destination, filter="data")
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="69f534730669f59051a453d9833a0be88695f263")
    for module, ref in REFS.items():
        parser.add_argument(f"--ref-{module[:2]}", default=ref)
    parser.add_argument("--prepare-consumer-locks", action="store_true")
    parser.add_argument("--docker", action="store_true", help="Also run isolated full Docker smoke")
    args = parser.parse_args()
    repo = Path(command(["git", "rev-parse", "--show-toplevel"]).decode().strip())
    prefix = ROOT.relative_to(repo).as_posix()
    output = ROOT / "02_api_backend/runtime" / f"auth-candidate-{uuid4().hex[:10]}"
    output.mkdir(parents=True)
    snapshot = output / "snapshot"
    snapshot.mkdir()
    report = {"started_at": datetime.now(UTC).isoformat(), "refs": {}, "locks": {}}
    print(f"Candidate report: {output}", flush=True)
    try:
        report["refs"]["base"] = export(repo, args.base_ref, prefix, snapshot)
        candidate = snapshot / prefix
        for module in REFS:
            report["refs"][module] = export(
                repo, getattr(args, f"ref_{module[:2]}"), f"{prefix}/{module}", snapshot
            )
        # Overlay only module 02 from this checkout, including new source/test files.
        shutil.rmtree(candidate / "02_api_backend")
        files = (
            command(
                [
                    "git",
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                    "--",
                    "02_api_backend",
                ],
                ROOT,
            )
            .decode()
            .split("\0")
        )
        report["02_files_sha256"] = {}
        for name in filter(None, files):
            source = ROOT / name
            if source.is_file():
                target = candidate / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                report["02_files_sha256"][name] = hashlib.sha256(target.read_bytes()).hexdigest()
        report["refs"]["02_head"] = command(["git", "rev-parse", "HEAD"]).decode().strip()
        environment = dict(
            os.environ,
            MINIPROJECT_ROOT=str(candidate),
            APP_ENV="test",
            GEMINI_API_KEY="",
            OPENAI_API_KEY="",
            UV_NO_PROGRESS="1",
        )
        environment.pop("VIRTUAL_ENV", None)

        def run(label, arguments):
            with (output / f"{label}.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    arguments,
                    cwd=candidate,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=1800 if label == "docker" else 900,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            print(f"{label}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
            return result.returncode == 0

        for project in PROJECTS:
            label = project.replace("/", "-")
            valid = run(
                f"lock-{label}", ["uv", "lock", "--project", project, "--check", "--offline"]
            )
            state = {"original_valid": valid}
            report["locks"][project] = state
            if not valid and args.prepare_consumer_locks and not project.startswith("02_"):
                lock = candidate / project / "uv.lock"
                before = lock.read_text(encoding="utf-8")
                state["prepared"] = run(f"prepare-{label}", ["uv", "lock", "--project", project])
                if state["prepared"]:
                    patch = "".join(
                        difflib.unified_diff(
                            before.splitlines(keepends=True),
                            lock.read_text(encoding="utf-8").splitlines(keepends=True),
                            fromfile=f"a/{prefix}/{project}/uv.lock",
                            tofile=f"b/{prefix}/{project}/uv.lock",
                        )
                    )
                    # Git patch contexts must retain LF even on a Windows host.
                    (output / f"{label}.patch").write_text(patch, encoding="utf-8", newline="\n")
                    state["prepared_valid"] = run(
                        f"prepared-lock-{label}",
                        ["uv", "lock", "--project", project, "--check", "--offline"],
                    )
        report["backend_tests"] = run(
            "backend-tests",
            [
                "uv",
                "run",
                "--project",
                "02_api_backend/full",
                "--locked",
                "pytest",
                "02_api_backend/tests",
                "02_api_backend/integration/tests",
                "02_api_backend/full/tests",
                "-q",
                "-W",
                "error",
            ],
        )
        if args.docker:
            report["docker"] = run(
                "docker",
                [
                    sys.executable,
                    "02_api_backend/scripts/docker_full_smoke.py",
                ],
            )
        # Prepared patches are not merged locks; this report never certifies all modules.
        report["consumer_locks_ready"] = all(s["original_valid"] for s in report["locks"].values())
        report["whole_system_verified"] = False
        return (
            0
            if (
                report["consumer_locks_ready"]
                and report["backend_tests"]
                and report.get("docker", True)
            )
            else 1
        )
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
