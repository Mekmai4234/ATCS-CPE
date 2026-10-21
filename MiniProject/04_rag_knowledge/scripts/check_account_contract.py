"""Test 04 against a pinned 02 Git revision without editing another module's checkout."""

import argparse
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-ref", required=True)
    parser.add_argument(
        "--docker-image", help="Use this already-built 04 test image instead of host"
    )
    args = parser.parse_args()
    module = Path(__file__).resolve().parents[1]
    root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=module,
            text=True,
        ).strip()
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.backend_ref}^{{commit}}"],
        cwd=root,
        text=True,
    ).strip()
    target = module / "runtime" / "account-contract" / revision
    archive = subprocess.check_output(
        [
            "git",
            "archive",
            "--format=zip",
            revision,
            "MiniProject/02_api_backend/src",
        ],
        cwd=root,
    )
    prefix = "MiniProject/02_api_backend/"
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        for item in package.infolist():
            if item.is_dir() or not item.filename.startswith(prefix):
                continue
            destination = (target / item.filename[len(prefix) :]).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("Unsafe archive path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(package.read(item))
    source = target / "src"
    if not (source / "youtube_backend" / "auth.py").is_file():
        raise ValueError("Selected backend revision has no account contract")
    print(f"Testing module 04 with backend revision {revision}", flush=True)
    pytest = [
        "-m",
        "pytest",
        "tests",
        "-q",
        "-W",
        "error",
        "-o",
        "cache_dir=/tmp/yk04-account-cache",
    ]
    if args.docker_image:
        command = [
            "docker",
            "run",
            "--rm",
            "--init",
            "--network",
            "none",
            "--mount",
            f"type=bind,source={source},target=/auth02,readonly",
            "-e",
            "PYTHONPATH=/auth02",
            "-e",
            "APP_ENV=test",
            "-e",
            "GEMINI_API_KEY=",
            "-e",
            "RUN_LIVE_EMBEDDING_TESTS=0",
            "--entrypoint",
            "python",
            args.docker_image,
            *pytest,
        ]
        return subprocess.call(command, cwd=module)
    environment = dict(
        os.environ,
        PYTHONPATH=str(source),
        PYTHONDONTWRITEBYTECODE="1",
        MINIPROJECT_ROOT=str(module.parent),
        RUN_LIVE_EMBEDDING_TESTS="0",
    )
    pytest[-1] = "cache_dir=" + str(target / "pytest-cache")
    return subprocess.call(
        [sys.executable, *pytest, f"--junitxml={target / 'tests.xml'}"], cwd=module, env=environment
    )


if __name__ == "__main__":
    raise SystemExit(main())
