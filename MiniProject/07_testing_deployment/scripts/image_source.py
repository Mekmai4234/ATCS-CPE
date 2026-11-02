"""Fingerprint imported wheel contents and immutable transcript sources in Docker."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def capture():
    files = {}
    for name in (
        "youtube_backend",
        "youtube_ingestion",
        "youtube_rag",
        "youtube_answers",
        "youtube_agent",
    ):
        root = Path(next(iter(importlib.util.find_spec(name).submodule_search_locations)))
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files[name + "/" + path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    for path in sorted(Path("/app/Transcript").glob("*")):
        if path.suffix in {".txt", ".json"}:
            files["Transcript/" + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    web = Path("/app/01_web_app")
    excluded = {
        "node_modules",
        "dist",
        "runtime",
        "test-results",
        "playwright-report",
        "__pycache__",
    }
    for path in sorted(web.rglob("*")):
        if (
            path.is_file()
            and not excluded.intersection(path.relative_to(web).parts)
            and not path.name.startswith(".env")
        ):
            files["01_web_app/" + path.relative_to(web).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return dict(
        mode="docker-image",
        files=files,
        source_sha256=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
        live_google_verified=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["record", "verify"])
    parser.add_argument("--record", type=Path, default=Path("/app/image-source.json"))
    args = parser.parse_args()
    actual = capture()
    if args.action == "record":
        args.record.write_text(json.dumps(actual, indent=2), encoding="utf-8")
    elif json.loads(args.record.read_text(encoding="utf-8")) != actual:
        raise ValueError("Imported image code/source fingerprint changed")
    print(actual["source_sha256"])


if __name__ == "__main__":
    main()
