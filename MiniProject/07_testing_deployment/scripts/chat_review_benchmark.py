"""Synthetic local HTTP baseline, isolated SQLite only; no AI/network/real account data."""

import argparse
import json
import math
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from source import context
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.fixture_adapter import FixtureAdapters
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.moderation import classify
from youtube_backend.repository import Repository


def measure(callback, samples):
    values = []
    for _ in range(samples):
        start = time.perf_counter()
        callback()
        values.append((time.perf_counter() - start) * 1000)
    ordered = sorted(values)
    return dict(
        n=samples,
        first_ms=values[0],
        p50_ms=ordered[math.ceil(samples * 0.5) - 1],
        p95_ms=ordered[math.ceil(samples * 0.95) - 1],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", action="store_true")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 20 <= args.samples <= 1000 or not 100 <= args.rows <= 10000:
        parser.error("Use 20..1000 samples and 100..10000 synthetic rows")
    provenance = context(args.checkout)
    corpus = json.loads(
        (Path(__file__).parents[1] / "fixtures/chat_policy_th_en.json").read_text("utf-8")
    )
    with tempfile.TemporaryDirectory(prefix="vb07-review-benchmark-") as temporary:
        settings = Settings(
            _env_file=None,
            app_env="test",
            auth_enabled=True,
            adapter_mode="fixture",
            session_cookie_secure=False,
            google_client_id="benchmark-fixture",
            chat_review_enabled=True,
            chat_review_admin_ids=["benchmark-admin"],
            database_url=f"sqlite:///{(Path(temporary) / 'app.db').as_posix()}",
        )
        database = Database(settings.database_url)
        upgrade_database(database)
        repo = Repository(database, settings)
        token = actor_id.set("benchmark-admin")
        try:
            with database.write() as c:
                c.execute(
                    db.users.insert().values(
                        user_id="benchmark-admin",
                        google_sub="benchmark-admin",
                        role="admin",
                        status="active",
                        created_at=1,
                        updated_at=1,
                    )
                )
                for i in range(args.rows):
                    cid, mid = f"conversation-{i}", f"assistant-{i}"
                    c.execute(
                        db.conversations.insert().values(
                            conversation_id=cid, owner_id="benchmark-admin", created_at=i
                        )
                    )
                    job = repo._new_job(
                        c, "chat", {"request": {}, "sources": []}, conversation_id=cid
                    )
                    c.execute(
                        db.jobs.update()
                        .where(db.jobs.c.job_id == job["job_id"])
                        .values(
                            state="completed",
                            result={"answer": "Synthetic answer", "visibility": "published"},
                        )
                    )
                    for role, message_id in (("user", f"user-{i}"), ("assistant", mid)):
                        c.execute(
                            db.messages.insert().values(
                                message_id=message_id,
                                conversation_id=cid,
                                job_id=job["job_id"],
                                role=role,
                                scope=[],
                                content=f"Synthetic RAG {i}",
                                created_at=i,
                            )
                        )
                    c.execute(
                        db.review["feedback"]
                        .insert()
                        .values(
                            owner_id="benchmark-admin",
                            message_id=mid,
                            rating="dislike",
                            reason="incorrect",
                            comment="",
                            revision=1,
                            created_at=i,
                            updated_at=i,
                        )
                    )
                    c.execute(
                        db.review["cases"]
                        .insert()
                        .values(
                            case_id=f"case-{i}",
                            owner_id="benchmark-admin",
                            message_id=mid,
                            source="user",
                            label="user_dissatisfied",
                            status="new",
                            notes="",
                            created_at=i,
                            updated_at=i,
                        )
                    )
        finally:
            actor_id.reset(token)
        app = create_app(settings, database, FixtureAdapters(repo, settings))
        with TestClient(app) as client:
            challenge = client.get("/api/auth/challenge").json()
            app.state.auth.verifier = lambda credential, audience: dict(
                sub="benchmark-admin",
                aud=audience,
                iss="https://accounts.google.com",
                exp=time.time() + 300,
                nonce=challenge["nonce"],
            )
            login = client.post(
                "/api/auth/google",
                headers={"Origin": settings.web_origin},
                json={"credential": "synthetic", "csrf_token": challenge["csrf_token"]},
            )
            assert login.status_code == 200
            client.headers.update(
                {"Origin": settings.web_origin, "X-CSRF-Token": login.json()["csrf_token"]}
            )

            def listing():
                response = client.get("/api/admin/chat-reviews", params={"limit": 20, "q": "RAG"})
                assert response.status_code == 200 and len(response.json()["items"]) == 20

            def feedback():
                response = client.put(
                    "/api/messages/assistant-0/feedback", json={"rating": "dislike"}
                )
                assert response.status_code == 200

            rule_results = measure(
                lambda: [classify(case["text"]) for case in corpus["cases"]], args.samples
            )
            listing_results = measure(listing, args.samples)
            feedback_results = measure(feedback, args.samples)
        report = dict(
            source_revision=provenance["revision"],
            source_sha256=provenance["source_sha256"],
            synthetic=True,
            provider_calls=0,
            rows=args.rows,
            page_size=20,
            local_corpus_batch=dict(case_count=len(corpus["cases"]), **rule_results),
            review_http_page=listing_results,
            idempotent_feedback_http=feedback_results,
            semantic_accuracy_verified=False,
            improvement_claimed=False,
            limitations=(
                "One local SQLite fixture; includes audit writes; "
                "not production concurrency or model latency."
            ),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
