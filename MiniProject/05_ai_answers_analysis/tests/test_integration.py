"""Real 02 HTTP/worker/SQLite and 04 Chroma; labelled model/ingestion doubles."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from conftest import VIDEO_A, VIDEO_B, ScriptedModel, metadata
from google import genai
from google.genai import types
from youtube_agent.config import AgentSettings
from youtube_agent.models import ModelReply
from youtube_agent.service import AgentService
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.main import create_app
from youtube_backend.migration import upgrade_database
from youtube_backend.repository import Repository
from youtube_backend.schemas import Segment, Source, TranscriptResult
from youtube_backend.worker import Worker
from youtube_rag.config import RagSettings
from youtube_rag.embeddings import FixtureEmbedder
from youtube_rag.manifest import initialize

from youtube_answers.config import AnswerSettings
from youtube_answers.gemini import GeminiModel
from youtube_answers.integration import AnswerAdapters, RagKnowledge
from youtube_answers.team import TeamAdapters


class FixtureIngestion:
    async def ingest(self, video_id, context):
        context.check()
        return TranscriptResult(
            video_id=video_id,
            title=f"[FIXTURE] RAG {video_id}",
            language="th",
            source="fixture",
            segments=[
                Segment(
                    segment_id=f"s{i}",
                    text=text,
                    start_seconds=i * 10,
                    duration_seconds=10,
                )
                for i, text in enumerate(
                    [
                        "[FIXTURE] RAG retrieves evidence before answering questions.",
                        "[FIXTURE] คำตอบต้องมีหลักฐานและอ้างอิงวิดีโอต้นทาง",
                    ]
                )
            ],
        )

    async def close(self):
        pass


class ComparisonAgentModel:
    async def decide(self, history, timeout):
        observations = [h for h in history if h["role"] == "tool"]
        if not observations:
            return ModelReply("compare_videos", {"video_ids": [VIDEO_A, VIDEO_B]}, metadata())
        data = observations[-1]["result"]
        return ModelReply(
            "finish_research",
            {
                "content": "[FIXTURE] Compared the supplied videos.",
                "citation_ids": [c["chunk_id"] for c in data["evidence"]],
            },
            metadata(),
        )

    async def close(self):
        pass


@pytest.fixture
async def integrated(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        adapter_mode="custom",
        adapter_factory="youtube_answers.integration:create_adapters",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        job_lease_seconds=120,
        job_retry_base_seconds=0,
    )
    db = Database(settings.database_url)
    upgrade_database(db)
    initialize(db)
    repo = Repository(db, settings)
    rag_config = RagSettings(
        _env_file=None,
        embedding_provider="fixture",
        embedding_model="fixture-hash-v1",
        embedding_dimensions=64,
        chroma_persist_dir=tmp_path / "chroma",
        chunk_target_tokens=160,
        chunk_overlap_tokens=16,
    )
    model = ScriptedModel()
    answers = AnswerAdapters(
        settings=settings,
        repository=repo,
        answer_settings=AnswerSettings(_env_file=None),
        model=model,
        rag_settings=rag_config,
        embedder=FixtureEmbedder(rag_config),
    )
    agent = AgentService(
        AgentSettings(_env_file=None),
        ComparisonAgentModel(),
        RagKnowledge(answers.rag),
        analyzer=answers.analyze,
    )
    adapters = TeamAdapters(answers, FixtureIngestion(), agent)
    worker = Worker(repo, adapters, settings)
    app = create_app(settings, db, adapters)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for video in (VIDEO_A, VIDEO_B):
            response = await client.post(
                "/api/videos/import",
                json={"urls": [f"https://youtu.be/{video}"]},
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["jobs"][0]["job_id"]
            await worker.run_once(job_id)
            assert repo.get_job(job_id)["stage"] == "ready", repo.get_job(job_id)
        yield SimpleNamespace(
            settings=settings,
            db=db,
            repo=repo,
            answers=answers,
            adapters=adapters,
            worker=worker,
            client=client,
            model=model,
        )
    await adapters.close()
    db.close()


async def test_http_chat_citations_history_and_database_reopen(integrated):
    env = integrated
    request = {"question": "RAG คืออะไร", "scope": {"video_ids": [VIDEO_A]}}
    response = await env.client.post(
        "/api/chat",
        json=request,
        headers={"Idempotency-Key": "answer-05"},
    )
    assert response.status_code in {200, 202}, response.text
    job_id = response.json()["job_id"]
    if response.status_code == 202:
        await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "completed", job
    result = job["result"]
    assert result["status"] == "answered"
    assert {c["video_id"] for c in result["citations"]} == {VIDEO_A}
    assert result["provider_metadata"]["provider"] == "fixture"
    replay = await env.client.post(
        "/api/chat",
        json=request,
        headers={"Idempotency-Key": "answer-05"},
    )
    assert replay.json()["job_id"] == job_id
    conversation_id = job["conversation_id"]
    history = await env.client.get(f"/api/conversations/{conversation_id}")
    assert history.status_code == 200 and len(history.json()["messages"]) == 2
    reopened = Database(env.settings.database_url)
    try:
        assert Repository(reopened, env.settings).get_job(job_id)["result"] == result
    finally:
        reopened.close()


@pytest.mark.parametrize("kind", ["summary", "compare"])
async def test_http_analysis_worker_polling(integrated, kind):
    env = integrated
    response = await env.client.post(
        "/api/analysis",
        json={
            "type": kind,
            "scope": {"video_ids": [VIDEO_A, VIDEO_B]},
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    await env.worker.run_once(job_id)
    job = (await env.client.get(f"/api/jobs/{job_id}")).json()
    assert job["state"] == "completed", job
    assert job["result"]["coverage"]["complete"]
    assert {c["video_id"] for c in job["result"]["citations"]} == {VIDEO_A, VIDEO_B}


async def test_06_calls_real_05_comparison_through_research(integrated):
    env = integrated
    response = await env.client.post(
        "/api/research",
        json={
            "goal": "Compare RAG videos",
            "scope": {"video_ids": [VIDEO_A, VIDEO_B]},
        },
    )
    assert response.status_code == 202
    job_id = response.json()["run_id"]
    await env.worker.run_once(job_id)
    job = env.repo.get_job(job_id)
    assert job["state"] == "completed", job
    assert env.model.payloads[-1]["task"] == "compare"
    assert {c["video_id"] for c in job["result"]["citations"]} == {VIDEO_A, VIDEO_B}


async def test_authorized_job_cannot_read_another_video(integrated):
    env = integrated
    queued = env.repo.enqueue(
        "analysis",
        {
            "type": "summary",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    job = env.repo.claim(queued["job_id"])
    context = ExecutionContext(
        env.repo,
        job["job_id"],
        job["lease_token"],
        job["deadline_at"],
        env.settings,
    )
    source = Source.model_validate(job["payload"]["sources"][0])
    source.video_id = VIDEO_B
    with pytest.raises(AppError) as caught:
        await env.answers.analyze(
            {"type": "summary", "scope": {"video_ids": [VIDEO_B]}},
            [source],
            context,
        )
    assert caught.value.code == "invalid_scope"


@pytest.mark.parametrize("action", ["cancel", "delete"])
async def test_running_analysis_cancel_or_delete_cannot_publish(integrated, action):
    env = integrated
    started = asyncio.Event()

    async def waiting(data, timeout):
        started.set()
        await asyncio.sleep(0.05)
        return await ScriptedModel().generate(data, timeout)

    env.model.generate = waiting
    queued = env.repo.enqueue(
        "analysis",
        {
            "type": "summary",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    task = asyncio.create_task(env.worker.run_once(queued["job_id"]))
    await asyncio.wait_for(started.wait(), 15)
    if action == "delete":
        response = await env.client.delete(f"/api/videos/{VIDEO_A}")
        assert response.status_code == 202
    else:
        env.repo.cancel(queued["job_id"])
    await task
    job = env.repo.get_job(queued["job_id"])
    assert job["state"] in {"cancelled", "failed"}, job
    assert job["result"] is None


async def test_backend_rejects_invalid_model_citation(integrated):
    from youtube_answers.models import GeneratedAnswer

    env = integrated
    env.model.output = GeneratedAnswer.model_validate(
        {
            "status": "answered",
            "statements": [{"text": "Bad", "citation_ids": ["invented"]}],
        }
    )
    queued = env.repo.enqueue(
        "analysis",
        {
            "type": "summary",
            "scope": {"video_ids": [VIDEO_A]},
        },
    )
    await env.worker.run_once(queued["job_id"])
    job = env.repo.get_job(queued["job_id"])
    assert job["state"] == "failed" and job["error_code"] == "invalid_citation"
    assert job["result"] is None


async def test_real_sdk_wire_through_02_05_04(integrated):
    env = integrated
    calls = []

    def handler(request):
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 50})
        data = json.loads(request.content)
        calls.append(data)
        items = json.loads(data["contents"][0]["parts"][0]["text"])["untrusted_evidence"]
        refs = list(dict.fromkeys(c for n in items for c in n["citation_ids"]))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "status": "answered",
                                            "statements": [
                                                {
                                                    "text": "[FIXTURE SDK] Cited findings.",
                                                    "citation_ids": refs,
                                                }
                                            ],
                                        }
                                    )
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "fixture-sdk-wire",
                "usageMetadata": {"promptTokenCount": 20},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = genai.Client(
        api_key="test-only-secret",
        vertexai=False,
        http_options=types.HttpOptions(
            httpx_async_client=http,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    model = GeminiModel(AnswerSettings(_env_file=None), client=client)
    env.answers.answers.model = model
    try:
        queued = env.repo.enqueue(
            "analysis",
            {
                "type": "compare",
                "scope": {"video_ids": [VIDEO_A, VIDEO_B]},
            },
        )
        await env.worker.run_once(queued["job_id"])
        job = env.repo.get_job(queued["job_id"])
        assert job["state"] == "completed", job
        assert job["result"]["provider_metadata"]["returned_model"] == "fixture-sdk-wire"
        assert len(calls) == 3
    finally:
        await http.aclose()


async def test_missing_index_returns_valid_partial_through_backend(integrated):
    from youtube_rag.manifest import active

    env = integrated
    # Simulate one unavailable index while retaining the backend's frozen ready sources.
    with env.db.write() as connection:
        connection.execute(active.delete().where(active.c.video_id == VIDEO_B))
    queued = env.repo.enqueue(
        "analysis",
        {
            "type": "compare",
            "scope": {"video_ids": [VIDEO_A, VIDEO_B]},
        },
    )
    await env.worker.run_once(queued["job_id"])
    job = env.repo.get_job(queued["job_id"])
    assert job["state"] == "completed", job
    result = job["result"]
    assert not result["coverage"]["complete"] and result["coverage"]["notes"]
    assert result["coverage"]["expected_chunks"] is None
    assert {c["video_id"] for c in result["citations"]} == {VIDEO_A}


async def test_team_close_is_idempotent(integrated):
    env = integrated
    await env.adapters.close()
    await env.adapters.close()
    assert env.model.closed


async def test_full_team_factory_constructs_shared_services_without_network(
    integrated, monkeypatch, tmp_path
):
    from youtube_answers import team

    for key, value in {
        "GEMINI_API_KEY": "test-only-secret",
        "EMBEDDING_PROVIDER": "gemini",
        "EMBEDDING_MODEL": "gemini-embedding-2",
        "EMBEDDING_DIMENSIONS": "1536",
        "CHROMA_PERSIST_DIR": str(tmp_path / "unused-live-store"),
    }.items():
        monkeypatch.setenv(key, value)
    settings = integrated.settings.model_copy(
        update={
            "backend_integration_profile": "live",
            "adapter_factory": "youtube_answers.team:create_adapters",
            "gemini_api_key": AnswerSettings(_env_file=None).gemini_api_key,
            "chroma_persist_dir": str(tmp_path / "unused-live-store"),
        }
    )
    adapters = await team.create_adapters(settings=settings, repository=integrated.repo)
    try:
        assert adapters.agent.knowledge.rag is adapters.answers.rag
        assert adapters.agent.analyzer == adapters.answers.analyze
        assert adapters.capabilities["ingest"] and adapters.capabilities["answer"]
        assert adapters.answers.rag.vectors.process is None  # No requests or subprocess work.
        assert not (tmp_path / "unused-live-store").exists()
    finally:
        await adapters.close()


async def test_full_team_factory_rejects_offline_profile(integrated):
    from youtube_answers import team

    settings = integrated.settings.model_copy(update={"backend_integration_profile": "offline"})
    with pytest.raises(AppError) as caught:
        await team.create_adapters(settings=settings, repository=integrated.repo)
    assert caught.value.code == "integration_configuration"


async def test_real_acceptance_rejects_seeded_fixture_transcripts_despite_live_health(integrated):
    from youtube_answers.acceptance import AcceptanceCase, AcceptancePlan, AcceptanceRunner

    plan = AcceptancePlan(
        videos=[f"https://youtu.be/{VIDEO_A}", f"https://youtu.be/{VIDEO_B}"],
        expected_model="gemini-3.5-flash",
        cases=[
            AcceptanceCase(
                id="qa",
                category="supported",
                kind="chat",
                request={"question": "RAG", "scope": {"video_ids": [VIDEO_A]}},
                review_criteria="Review actual imported evidence.",
            )
        ],
    )
    with pytest.raises(AppError) as caught:
        await AcceptanceRunner(integrated.client).run(plan)
    assert caught.value.code == "acceptance_synthetic_source"
