"""Create an immutable, reviewable integration candidate without merging pending PRs."""

import argparse
import hashlib
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
    parser.add_argument("--manifest", type=Path, help="Exact base and module commits to test")
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument(
        "--baseline-lock",
        action="store_true",
        help="Use historical develop lock; never for auth acceptance",
    )
    parser.add_argument(
        "--module-ref",
        action="append",
        default=[],
        metavar="MODULE=REF",
        help="Overlay only this numbered module from an explicitly selected Git ref",
    )
    args = parser.parse_args()
    if args.manifest:
        if args.module_ref or args.baseline_lock:
            parser.error("A pinned auth manifest cannot be mixed with overrides/baseline lock")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        args.base = manifest["base"]
        args.module_ref = [f"{module}={ref}" for module, ref in manifest["modules"].items()]
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
        if args.manifest and (len(ref) != 40 or ref != selections[module]):
            parser.error("Manifest module refs must be immutable full commit SHAs")
    if args.manifest and (set(selections) != allowed or args.base != base):
        parser.error("Manifest must pin the base and every 01-06 module")
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
        tooling_commit=git("rev-parse", "HEAD").decode().strip(),
        tooling_dirty=bool(git("status", "--porcelain", "--", "MiniProject/07_testing_deployment")),
        lock_profile="historical-baseline" if args.baseline_lock else "auth-candidate",
    )
    if args.baseline_lock:
        shutil.copyfile(MODULE / "locks/develop-69f5347.uv.lock", output / MODULE.name / "uv.lock")
    provenance["lock_sha256"] = hashlib.sha256(
        (output / MODULE.name / "uv.lock").read_bytes()
    ).hexdigest()
    fingerprint = hashlib.sha256()
    for path in sorted((output / MODULE.name).rglob("*")):
        if path.is_file():
            fingerprint.update(path.relative_to(output / MODULE.name).as_posix().encode())
            fingerprint.update(b"\0" + path.read_bytes() + b"\0")
    provenance["tooling_sha256"] = fingerprint.hexdigest()
    (output / "candidate.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(output)
    if args.github_output:
        import os

        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"root={output}\n")
    print("Run uv lock --check, then uv sync --locked. Never regenerate a verification lock.")


if __name__ == "__main__":
    main()
