"""Offline validate/dry-run/import. Import is an explicit trusted local operation."""

import argparse
import json
from pathlib import Path

from .documents import load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "dry-run", "import"])
    parser.add_argument("--root", type=Path, default=Path("Transcript"))
    args = parser.parse_args()
    documents = load(args.root)
    report = [
        dict(
            document_id=d.document_id,
            video_id=d.video_id,
            sha256=d.sha256,
            segments=len(d.segments),
            unknown_ends=sum(s.end_seconds is None for s in d.segments),
        )
        for d in documents
    ]
    if args.action == "import":
        from youtube_backend.config import Settings
        from youtube_backend.database import Database
        from youtube_backend.document_store import publish

        database = Database(Settings().database_url)
        try:
            database.check_schema()
            for document, row in zip(documents, report, strict=True):
                row.update(publish(database, document.model_dump()))
        finally:
            database.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
