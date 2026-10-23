"""Record/verify the actual working checkout; never archive or replace application sources."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = [
    "01_web_app",
    "02_api_backend",
    "03_video_ingestion",
    "04_rag_knowledge",
    "05_ai_answers_analysis",
    "06_research_learning_agent",
    "07_testing_deployment",
]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def validate_checkout_workflow(text):
    if any(token in text for token in ("candidate.py", "--manifest", "steps.candidate.outputs")):
        raise ValueError("Default checkout workflow cannot replace source with pinned archives")


def capture(root=ROOT):
    root = Path(root).resolve()
    repository = Path(git(root, "rev-parse", "--show-toplevel").decode().strip())
    workflow = repository / ".github/workflows/miniproject-offline.yml"
    if workflow.is_file():
        validate_checkout_workflow(workflow.read_text(encoding="utf-8"))
    prefix = root.relative_to(repository).as_posix()
    paths = [f"{prefix}/{name}" for name in MODULES]
    paths.append(".github/workflows")
    names = (
        git(
            repository, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *paths
        )
        .decode()
        .split("\0")
    )
    files = {}
    for name in sorted(set(names) - {""}):
        path = repository / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Source file missing or symlinked: " + name)
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return dict(
        mode="checkout",
        revision=git(repository, "rev-parse", "HEAD").decode().strip(),
        dirty=bool(git(repository, "status", "--porcelain", "--", *paths)),
        source_sha256=fingerprint,
        files=files,
        live_google_verified=False,
    )


def verify(expected, root=ROOT):
    current = capture(root)
    if any(current[key] != expected[key] for key in ("mode", "revision", "source_sha256", "dirty")):
        raise ValueError("Checkout provenance changed; results cannot certify the recorded source")
    return current


def context(checkout=False):
    if checkout:
        return capture()
    path = ROOT / "candidate.json"
    if not path.is_file():
        raise ValueError(
            "Use --checkout for actual source, or run inside an explicit pinned candidate"
        )
    return dict(mode="pinned-candidate", **json.loads(path.read_text(encoding="utf-8")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["record", "verify"])
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "record":
            record = capture()
            args.record.parent.mkdir(parents=True, exist_ok=True)
            args.record.write_text(json.dumps(record, indent=2), encoding="utf-8")
        else:
            record = verify(json.loads(args.record.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        parser.exit(1, "Checkout source/provenance rejected. No pinned fallback was used.\n")
    print(json.dumps({k: record[k] for k in ("mode", "revision", "dirty", "source_sha256")}))


if __name__ == "__main__":
    main()
