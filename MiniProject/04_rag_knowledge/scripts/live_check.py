"""Explicit live check. A temporary ignored key file or stdin keeps credentials off argv.

Only synthetic fixtures are sent to Google's official Gemini API. Reports contain no key.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--key-file", type=Path)
    source.add_argument("--stdin-key", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    key = (
        args.key_file.read_text(encoding="utf-8").strip()
        if args.key_file
        else sys.stdin.readline().strip()
        if args.stdin_key
        else os.environ.get("GEMINI_API_KEY", "")
    )
    if not key:
        print("GEMINI_API_KEY is required for an explicit live check", file=sys.stderr)
        return 1
    os.environ.update(
        GEMINI_API_KEY=key,
        RUN_LIVE_EMBEDDING_TESTS="1",
        EMBEDDING_PROVIDER="gemini",
        EMBEDDING_MODEL="gemini-embedding-2",
        EMBEDDING_DIMENSIONS="1536",
        EMBEDDING_TOKENIZER="utf8-byte-budget-v1",
    )
    result = {"provider": "gemini", "model": "gemini-embedding-2"}
    try:
        test = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_embeddings.py",
                "-m",
                "live",
                "-q",
                "-p",
                "no:cacheprovider",
                "-W",
                "error",
                "--tb=short",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        result["live_pytest_passed"] = test.returncode == 0
        result["live_pytest_summary"] = test.stdout.strip().splitlines()[-1:]
        if test.returncode == 0:
            from youtube_rag.evaluation import evaluate

            with tempfile.TemporaryDirectory(prefix="yk04-gemini-live-") as directory:
                state = Path(directory)
                result["evaluation"] = asyncio.run(evaluate(state, live=True))
                result["restart"] = asyncio.run(evaluate(state, live=True, phase="verify"))
        result["passed"] = (
            test.returncode == 0
            and result.get("restart", {}).get("restart_verified", False)
            and all(
                result.get(phase, {}).get("scope_checks_passed", False)
                and result.get(phase, {}).get("reference_recall_at_3") == 1.0
                for phase in ("evaluation", "restart")
            )
        )
    except Exception as exc:
        # Never serialize provider exceptions or HTTP request details.
        result["passed"] = False
        result["error"] = getattr(exc, "code", type(exc).__name__)
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    text = json.dumps(result, ensure_ascii=False, indent=2).replace(key, "[redacted]")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
