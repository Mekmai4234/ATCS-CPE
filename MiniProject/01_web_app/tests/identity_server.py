"""Loopback-only browser fixture: real module-02 routes, replaced external Google verifier.

Never shipped by the frontend build. No fixture routes or verifier are added to module 02.
The runner provides an isolated archive, database and environment with APP_ENV=test.
"""
import json
import os
import time

import uvicorn

from youtube_backend import database as db
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database


def main():
    if os.environ.get("WEB_IDENTITY_TEST") != "true":
        raise SystemExit("Test fixture requires explicit WEB_IDENTITY_TEST=true")
    settings = Settings()
    if settings.app_env != "test" or settings.api_host != "127.0.0.1":
        raise SystemExit("Only isolated loopback test mode is supported")
    database = Database(settings.database_url)
    upgrade_database(database)
    # Only the initial fixture administrator is seeded, independently of first login.
    with database.write() as connection:
        connection.execute(db.users.insert().values(
            user_id="fixture-admin", google_sub="fixture-admin", email="admin@example.test",
            name="Fixture Admin", picture=None, role="admin", status="active",
            created_at=time.time(), updated_at=time.time(),
        ))
    app = create_app(settings, database)

    def verifier(credential, audience):
        claims = json.loads(credential)
        if not claims["sub"].startswith("fixture-"):
            raise ValueError("Unknown fixture identity")
        return {**claims, "aud": audience, "iss": "https://accounts.google.com", "exp": time.time() + 300}

    app.state.auth.verifier = verifier
    uvicorn.run(app, host="127.0.0.1", port=settings.api_port, log_level="warning")


if __name__ == "__main__":
    main()
