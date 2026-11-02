"""Local Docker entry. Provider availability never grants access to documents.

AI requests still pass the unchanged execution broker and its per-call policy.
Production HTTPS/review remains in compose.auth.yaml, not this local profile.
"""

import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url
from youtube_backend.database import Database
from youtube_backend.full import FullSettings
from youtube_backend.full_pair import check_pair, initialize_pair
from youtube_backend.migration import upgrade_database


def main():
    settings = FullSettings(_env_file=None)
    os.environ.update(settings.child_environment())
    action = sys.argv[1]
    if action == "migrate":
        path = Path(make_url(settings.database_url).database)
        if not path.exists():
            initialize_pair(settings)
        else:
            database = Database(settings.database_url)
            try:
                with database.engine.connect() as c:
                    from sqlalchemy import inspect

                    existing = inspect(c).has_table("backend02_full_pair")
                if not existing:
                    raise ValueError("Existing unbound database needs explicit paired migration")
                upgrade_database(database)
            finally:
                database.close()
        check_pair(settings)
        print("Migration and paired storage verified")
    elif action == "validate":
        from youtube_ingestion.documents import load

        documents = load(Path("/app/Transcript"))
        if len(documents) != 5 or sum(len(d.segments) for d in documents) != 934:
            raise ValueError("Release transcript inventory differs")
        print("5 documents / 934 passages verified; no provider calls")
    elif action in {"api", "worker"}:
        check_pair(settings)
        from youtube_backend.cli import api, worker

        sys.argv = [sys.argv[0]]
        (api if action == "api" else worker)()
    else:
        raise ValueError("Unknown local runtime action")


if __name__ == "__main__":
    main()
