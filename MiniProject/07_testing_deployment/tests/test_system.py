"""02/03/04/05/06 together; fake external caption/model providers, real domain services."""

from contextlib import asynccontextmanager

import httpx
import pytest
from youtube_agent.config import AgentSettings
from youtube_agent.models import ModelReply
from youtube_agent.service import AgentService
from youtube_answers.config import AnswerSettings
from youtube_answers.integration import AnswerAdapters, RagKnowledge
from youtube_answers.models import Generated, GeneratedAnswer
from youtube_answers.team import TeamAdapters
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.schemas import ProviderMetadata
from youtube_backend.worker import Worker
from youtube_ingestion.captions import remote_error
from youtube_ingestion.config import IngestionSettings
from youtube_ingestion.models import Metadata
from youtube_ingestion.service import IngestionService
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.manifest import initialize

A, B, MISSING = "dQw4w9WgXcQ", "jNQXAC9IVRw", "NoCaption01"


def metadata():
    return ProviderMetadata(
        provider="fixture", requested_model="fixture", returned_model="fixture07", latency_ms=1
    )


class CaptionProvider:
    async def fetch(self, video_id, languages, timeout):
        if video_id == MISSING:
            raise remote_error("no_transcript")
        return dict(
            video_id=video_id,
            language="th",
            is_generated=False,
            segments=[
                dict(
                    text="[FIXTURE] RAG retrieves evidence before answering.",
                    start=0.0,
                    duration=10.0,
                ),
                dict(text="[FIXTURE] คำตอบอ้างอิงหลักฐานจากวิดีโอ", start=10.0, duration=10.0),
            ],
        )

    async def close(self):
        pass


class MetadataProvider:
    async def fetch(self, video_id, timeout):
        return Metadata(title=f"[FIXTURE07] {video_id}")

    async def close(self):
        pass


class AnswerModel:
    async def generate(self, payload, timeout):
        refs = list(
            dict.fromkeys(
                ref for item in payload["untrusted_evidence"] for ref in item["citation_ids"]
            )
        )
        return Generated(
            GeneratedAnswer.model_validate(
                dict(
                    status="answered",
                    statements=[
                        dict(text="[FIXTURE07] RAG uses retrieved evidence.", citation_ids=refs),
                    ],
                )
            ),
            metadata(),
        )

    async def close(self):
        pass


class ResearchModel:
    async def generate(self, request, records, schema, timeout):
        from youtube_agent.models import Generated as AgentGenerated

        assert request["type"] == "quiz" and records
        content = schema.model_validate(
            dict(
                questions=[
                    dict(
                        question="[FIXTURE07] What does RAG retrieve?",
                        answer="Evidence",
                        explanation=records[0].text,
                        citations=[records[0].chunk_id],
                    )
                ]
            )
        )
        return AgentGenerated(content, metadata())

    async def decide(self, history, timeout):
        observations = [entry for entry in history if entry["role"] == "tool"]
        if not observations:
            return ModelReply("compare_videos", {"video_ids": [A, B]}, metadata())
        evidence = observations[-1]["result"]["evidence"]
        return ModelReply(
            "finish_research",
            dict(
                content="[FIXTURE07] Both sources were compared.",
                citation_ids=[entry["chunk_id"] for entry in evidence],
            ),
            metadata(),
        )

    async def close(self):
        pass


@asynccontextmanager
async def system(state, *, auth=False, configure_app=None):
    identity_settings = {}
    if "auth_enabled" in Settings.model_fields:
        identity_settings = dict(
            auth_enabled=auth, session_cookie_secure=False, google_client_id="fixture07-client"
        )
    settings = Settings(
        _env_file=None,
        app_env="test",
        adapter_mode="custom",
        adapter_factory="youtube_answers.team:create_adapters",
        backend_integration_profile="offline",
        database_url=f"sqlite:///{(state / 'app.db').as_posix()}",
        job_lease_seconds=120,
        job_retry_base_seconds=0,
        **identity_settings,
    )
    database = Database(settings.database_url)
    upgrade_database(database)
    initialize(database)
    repo = Repository(database, settings)
    rag = RagSettings(
        _env_file=None,
        embedding_provider="fixture",
        embedding_model="fixture-hash-v1",
        embedding_dimensions=64,
        chroma_persist_dir=state / "chroma",
        chunk_target_tokens=160,
        chunk_overlap_tokens=16,
    )
    answers = AnswerAdapters(
        settings=settings,
        repository=repo,
        answer_settings=AnswerSettings(_env_file=None),
        model=AnswerModel(),
        rag_settings=rag,
        embedder=FixtureEmbedder(rag),
    )
    ingestion = IngestionService(
        IngestionSettings(_env_file=None), captions=CaptionProvider(), metadata=MetadataProvider()
    )
    agent = AgentService(
        AgentSettings(_env_file=None),
        ResearchModel(),
        RagKnowledge(answers.rag),
        analyzer=answers.analyze,
    )
    adapters = TeamAdapters(answers, ingestion, agent)
    app = create_app(settings, database, adapters)
    if configure_app:
        configure_app(app)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client, Worker(repo, adapters, settings)
    finally:
        await adapters.close()
        database.close()


async def finish(client, worker, path, body):
    response = await client.post(path, json=body)
    assert response.status_code in {200, 202}, response.text
    key = "run_id" if path == "/api/research" else "job_id"
    job_id = response.json()[key]
    await worker.run_once(job_id)
    result = (await client.get(f"/api/jobs/{job_id}")).json()
    assert result["state"] == "completed", result
    return result


@pytest.mark.asyncio
async def test_import_normalize_index_chat_compare_and_agent(tmp_path):
    async with system(tmp_path) as (client, worker):
        response = await client.post(
            "/api/videos/import",
            json=dict(urls=[f"https://youtu.be/{video}" for video in (A, B, MISSING)]),
        )
        jobs = response.json()["jobs"]
        for item in jobs:
            await worker.run_once(item["job_id"])
        for item, expected in zip(jobs, ["ready", "ready", "no_transcript"], strict=True):
            job = (await client.get(f"/api/jobs/{item['job_id']}")).json()
            assert job["stage"] == expected, job
        chat = await finish(
            client, worker, "/api/chat", dict(question="RAG คืออะไร", scope=dict(video_ids=[A]))
        )
        citations = chat["result"]["citations"]
        assert citations and {c["video_id"] for c in citations} == {A}
        assert all(c["url"].startswith(f"https://www.youtube.com/watch?v={A}") for c in citations)
        assert all(0 <= c["start_seconds"] < c["end_seconds"] <= 20 for c in citations)
        analysis = await finish(
            client, worker, "/api/analysis", dict(type="compare", scope=dict(video_ids=[A, B]))
        )
        assert analysis["result"]["coverage"]["complete"]
        research = await finish(
            client,
            worker,
            "/api/research",
            dict(goal="Compare both videos", scope=dict(video_ids=[A, B])),
        )
        assert {c["video_id"] for c in research["result"]["citations"]} == {A, B}
        conversation_id = chat["conversation_id"]
    # New adapters, clients and SQLite connection; persisted history and vectors survive.
    async with system(tmp_path) as (client, worker):
        history = await client.get(f"/api/conversations/{conversation_id}")
        assert history.status_code == 200 and len(history.json()["messages"]) == 2
        await finish(
            client, worker, "/api/chat", dict(question="RAG evidence", scope=dict(video_ids=[A]))
        )
