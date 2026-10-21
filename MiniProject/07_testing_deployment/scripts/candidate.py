"""Create an immutable, reviewable integration candidate without merging pending PRs."""

import argparse
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from uuid import uuid4

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parent


def git(*args):
    return subprocess.check_output(
        ["git", "-C", str(ROOT.parent), "-c", "core.autocrlf=false", *args]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/develop")
    parser.add_argument(
        "--module-ref",
        action="append",
        default=[],
        metavar="MODULE=REF",
        help="Overlay only this numbered module from an explicitly selected Git ref",
    )
    args = parser.parse_args()
    base = git("rev-parse", "--verify", f"{args.base}^{{commit}}").decode().strip()
    selections = {}
    allowed = {
        p.name
        for p in ROOT.iterdir()
        if p.is_dir() and p.name[:2] in {"01", "02", "03", "04", "05", "06"}
    }
    for value in args.module_ref:
        module, ref = value.split("=", 1)
        if module not in allowed or module in selections:
            parser.error("Select each existing 01-06 module at most once")
        selections[module] = git("rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    output = MODULE / "runtime" / f"candidate-{uuid4().hex[:10]}"
    output.mkdir(parents=True)
    for module in sorted(allowed):
        revision = selections.get(module, base)
        archive = git("archive", "--format=zip", revision, f"MiniProject/{module}")
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            for entry in files.infolist():
                relative = Path(entry.filename).relative_to("MiniProject")
                target = (output / relative).resolve()
                if (
                    not target.is_relative_to(output.resolve())
                    or entry.external_attr >> 16 & 0o170000 == 0o120000
                ):
                    raise ValueError("Unsafe archive entry")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(files.read(entry))
    shutil.copytree(
        MODULE,
        output / MODULE.name,
        ignore=shutil.ignore_patterns(
            "runtime",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".env",
            ".env.*",
            ".git",
            "*.pem",
            "*.key",
        ),
    )
    provenance = dict(
        base=base,
        modules={m: selections.get(m, base) for m in sorted(allowed)},
        status="candidate only; not merged develop",
        live_google_verified=False,
    )
    (output / "candidate.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(output)
    print("Run uv lock in candidate/07_testing_deployment, then uv sync --locked there.")
    print("Do not copy the candidate lock back: it describes pending module dependencies.")


if __name__ == "__main__":
    main()
