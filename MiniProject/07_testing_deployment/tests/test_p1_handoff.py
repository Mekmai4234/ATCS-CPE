"""Actual 02/04/06 stores/services, synthetic external generation; no quota spending."""

import time
from types import SimpleNamespace

import pytest
from test_system import A, metadata, system
from test_tooling import load
from youtube_agent.models import Generated
from youtube_backend import database as db
from youtube_backend.auth import actor_id
from youtube_backend.database import Database
from youtube_backend.repository import Repository, digest
from youtube_backend.schemas import AnswerResult, Citation, Coverage
from youtube_backend.video_evidence import VERSION, verify_video_citation


@pytest.mark.asyncio
async def test_library_learning_publication_history_and_revocation(tmp_path):
    state = tmp_path / "state"
    async with system(state, auth=True) as (_, worker):
        repo = worker.repo
        with repo.db.write() as c:
            c.execute(
                db.users.insert().values(
                    user_id="p1-fixture",
                    google_sub="p1-fixture",
                    role="user",
                    status="active",
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )
        token = actor_id.set("p1-fixture")
        try:
            item = repo.import_urls([f"https://youtu.be/{A}"])[0]
            await worker.run_once(item["job_id"])
            assert repo.get_job(item["job_id"])["stage"] == "ready"
            native = dict(
                id="fixture-v1",
                kind="visual",
                text="A red card is visible. This is a replay, not another event.",
                start_seconds=2,
                end_seconds=4,
            )
            queued = repo.enqueue(
                "artifact",
                dict(
                    type="quiz",
                    topic="red card replay",
                    scope={"video_ids": [A]},
                    level="beginner",
                    days=2,
                ),
            )
            source = queued["payload"]["sources"][0]
            with repo.db.write() as c:
                c.execute(
                    db.v2["cache"]
                    .insert()
                    .values(
                        cache_id="b" * 64,
                        owner_id="p1-fixture",
                        video_id=A,
                        generation=source["generation"],
                        evidence_version=source["transcript_version"],
                        prompt_version=VERSION,
                        model=repo.settings.llm_model,
                        input_hash="a" * 64,
                        expires_at=time.time() + 3600,
                        data=dict(source=source, observations=[native]),
                    )
                )

            native_calls = []

            async def native_fixture(*args):
                native_calls.append(True)
                return AnswerResult(
                    status="answered",
                    answer="[FIXTURE] A red card",
                    citations=[
                        Citation(
                            citation_id=digest(native),
                            chunk_id=digest(native),
                            video_id=A,
                            title="A red card",
                            start_seconds=2,
                            end_seconds=4,
                            kind="video",
                            observation_cache_id="b" * 64,
                        )
                    ],
                    coverage=Coverage(
                        expected_videos=1,
                        processed_videos=1,
                        complete=False,
                        notes=["Sampled fixture only"],
                    ),
                    provider_metadata=metadata(),
                )

            async def generate(request, evidence, schema, timeout, **kwargs):
                assert evidence[0].model_dump()["text"] == native["text"]
                assert evidence[0].model_dump()["evidence_id"] == digest(native)
                return Generated(
                    schema.model_validate(
                        dict(
                            questions=[
                                dict(
                                    question="What is visible?",
                                    answer="A red card",
                                    explanation="The stored observation warns this is a replay.",
                                    citations=[digest(native)],
                                )
                            ]
                        )
                    ),
                    metadata(),
                )

            agent = worker.adapters.agent
            library_available = callable(getattr(agent.knowledge.rag, "evidence_library", None))
            agent.model = SimpleNamespace(generate=generate, close=agent.model.close)
            agent.media_answerer = native_fixture
            agent.media_selector = lambda _: True
            await worker.run_once(queued["job_id"])
            saved = repo.get_job(queued["job_id"])
            assert saved["state"] == "completed", saved["error_code"]
            assert len(native_calls) == (0 if library_available else 1)
            artifact_id = saved["result"]["artifact_ids"][0]
            artifact = repo.artifact(artifact_id)
            assert artifact["sources_available"]
            assert artifact["citations"][0]["kind"] == "video"
            assert artifact["content"]["questions"][0]["citations"] == [digest(native)]
            settings = worker.settings
            with repo.db.write() as c:
                c.execute(db.v2["cache"].update().values(expires_at=time.time() - 1))
        finally:
            actor_id.reset(token)
    # All clients are now closed. Expired reuse pointers must not erase citations.
    recovery = load("recovery")
    recovery.backup(state, tmp_path / "backup", stopped=True)
    recovery.restore(tmp_path / "backup", tmp_path / "restored")
    restored = tmp_path / "restored" / "app.db"
    database = Database(f"sqlite:///{restored.as_posix()}")
    settings = settings.model_copy(update={"database_url": f"sqlite:///{restored.as_posix()}"})
    repo = Repository(database, settings)
    token = actor_id.set("p1-fixture")
    try:
        assert repo.artifact(artifact_id)["content"] == artifact["content"]
        with database.read() as c:
            checked = verify_video_citation(
                repo,
                c,
                repo.get_job(queued["job_id"], internal=True),
                Citation.model_validate(artifact["citations"][0]),
            )
            assert checked["text"] == native["text"]
        with database.write() as c:
            c.execute(db.user_videos.delete().where(db.user_videos.c.user_id == "p1-fixture"))
        assert repo.artifact(artifact_id)["sources_available"] is False
    finally:
        actor_id.reset(token)
        database.close()
