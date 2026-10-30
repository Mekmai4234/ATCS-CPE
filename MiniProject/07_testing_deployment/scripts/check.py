"""Run independent suites in the 07 locked environment; keep artifacts inside 07."""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parent
MODULES = [
    "02_api_backend",
    "03_video_ingestion",
    "04_rag_knowledge",
    "05_ai_answers_analysis",
    "06_research_learning_agent",
]


def clean_environment():
    env = dict(os.environ)
    for key in list(env):
        if key.upper().startswith(
            (
                "GEMINI_",
                "OPENAI_",
                "EMBEDDING_",
                "CHROMA_",
                "ADAPTER_",
                "BACKEND_",
                "AGENT_",
                "ANSWER_",
                "LLM_",
                "CHUNK_",
                "RETRIEVAL_",
                "RUN_LIVE_",
                "INGEST_",
                "TRANSCRIPT_",
                "METADATA_",
                "YOUTUBE_",
                "GOOGLE_",
                "SESSION_",
                "AUTH_",
                "FREE_",
                "QUOTA_",
                "MEDIA_",
            )
        ) or key.upper() in {
            "DATABASE_URL",
            "MINIPROJECT_ROOT",
            "APP_ENV",
            "ENABLE_STREAMING",
            "MAX_CONTEXT_TOKENS",
        }:
            env.pop(key)
    env.update(
        GEMINI_API_KEY="",
        OPENAI_API_KEY="",
        RUN_LIVE_EMBEDDING_TESTS="0",
        APP_ENV="test",
        MINIPROJECT_ROOT=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        RUFF_CACHE_DIR=str(MODULE / "runtime" / "ruff-cache"),
    )
    return env


def commands(group, output):
    if group in {"all", "baseline"}:
        suites = [(p, [f"{p}/tests"]) for p in MODULES]
        suites.append(("02-integration", ["02_api_backend/integration/tests"]))
        suites.append(("02-full", ["02_api_backend/full/tests"]))
        for name, paths in suites:
            yield (
                name,
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *paths,
                    "-q",
                    "-W",
                    "error",
                    "-m",
                    "not live",
                    "--junitxml",
                    str(output / f"{name}.xml"),
                    "-o",
                    f"cache_dir={output / ('cache-' + name)}",
                ],
            )
    if group in {"all", "acceptance", "regressions"}:
        expression = (
            "regression"
            if group == "regressions"
            else "not regression and not auth and not free_tier_contract"
        )
        yield (
            "07-acceptance" if group != "regressions" else "07-regressions",
            [
                sys.executable,
                "-m",
                "pytest",
                "07_testing_deployment/tests",
                "-q",
                "-W",
                "error",
                "-m",
                expression,
                "--junitxml",
                str(output / f"07-{group}.xml"),
                "-o",
                f"cache_dir={output / 'cache-07'}",
            ],
        )
        if group == "all":
            yield (
                "07-regressions",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "07_testing_deployment/tests",
                    "-q",
                    "-W",
                    "error",
                    "-m",
                    "regression",
                    "--junitxml",
                    str(output / "07-regressions.xml"),
                    "-o",
                    f"cache_dir={output / 'cache-regressions'}",
                ],
            )
    if group == "auth":
        yield (
            "07-auth",
            [
                sys.executable,
                "-m",
                "pytest",
                "07_testing_deployment/tests/auth",
                "-q",
                "-W",
                "error",
                "--junitxml",
                str(output / "07-auth.xml"),
                "-o",
                f"cache_dir={output / 'cache-auth'}",
            ],
        )
    if group == "free-tier":
        yield (
            "07-free-tier-contract",
            [
                sys.executable,
                "-m",
                "pytest",
                "07_testing_deployment/tests/free_tier",
                "-q",
                "-W",
                "error",
                "--junitxml",
                str(output / "07-free-tier.xml"),
                "-o",
                f"cache_dir={output / 'cache-free-tier'}",
            ],
        )
    if group in {"all", "lint"}:
        paths = [*MODULES, "07_testing_deployment"]
        yield "lint", [sys.executable, "-m", "ruff", "check", *paths]
        yield "format", [sys.executable, "-m", "ruff", "format", "--check", *paths]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        choices=["all", "baseline", "acceptance", "regressions", "auth", "lint", "free-tier"],
        default="all",
    )
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--temp-root",
        type=Path,
        default=Path(os.environ.get("YK07_TEMP_ROOT", tempfile.gettempdir())),
        help="Short temporary-state parent; reports stay in 07/runtime",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = MODULE / "runtime" / stamp
    output.mkdir(parents=True)
    temp_root = args.temp_root.expanduser().resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="yk7-", dir=temp_root))
    results = []
    plan = list(commands(args.group, output))
    for index, (name, command) in enumerate(plan):
        started = time.monotonic()
        print(f"Running {name}", flush=True)
        if "pytest" in command:
            command.extend(["--basetemp", str(temporary / str(index))])
        code, log = run_command(command, clean_environment(), args.timeout)
        (output / f"{name}.log").write_bytes(log)
        item = dict(name=name, exit_code=code, seconds=round(time.monotonic() - started, 3))
        results.append(item)
        print(json.dumps(item), flush=True)
        (output / "report.json").write_text(
            json.dumps(
                dict(
                    mode="offline",
                    generated_at_utc=stamp,
                    temporary_state=str(temporary),
                    results=results,
                    complete=len(results) == len(plan),
                    live_quality_verified=False,
                    passed=(
                        all(r["exit_code"] == 0 for r in results)
                        if len(results) == len(plan)
                        else None
                    ),
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"Report: {output / 'report.json'}", flush=True)
    return int(any(r["exit_code"] != 0 for r in results))


def run_command(command, environment, timeout):
    options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **options,
    ) as process:
        try:
            log, _ = process.communicate(timeout=timeout)
            return process.returncode, log
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
            log, _ = process.communicate(timeout=15)
            return 124, log + b"\nSUITE TIMEOUT (owned process tree terminated)\n"


if __name__ == "__main__":
    sys.exit(main())
