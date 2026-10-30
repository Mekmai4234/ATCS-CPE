"""Actual 02 API/worker/SQLite and 04 persistent Chroma, offline model/embedding doubles."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from conftest import VIDEO_A, VIDEO_B, ScriptedModel, metadata
from google import genai
from google.genai import types
from member_helpers import OwnedRepository, login
from youtube_backend import database as backend_db
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

from youtube_agent.config import AgentSettings
from youtube_agent.gemini import GeminiModel
from youtube_agent.integration import AgentAdapters
from youtube_agent.models import ModelReply


class LearningModel(ScriptedModel):
    async def decide(self, history, timeout):
        observations = [h for h in history if h["role"] == "tool"]
        self.history.append(list(history))
        if not observations:
            return ModelReply("read_video_chunks", {}, metadata())
        if observations[-1]["name"] == "read_video_chunks":
            return ModelReply("create_learning_artifact", {"type": "study_plan"}, metadata())
        records = next(
            h["result"]["evidence"] for h in observations if h["name"] == "read_video_chunks"
        )
        return ModelReply(
            "finish_research",
            {
                "content": "[FIXTURE] Study the cited RAG evidence.",
                "citation_ids": [e["chunk_id"] for e in records],
            },
            metadata(),
        )


class OfflineAdapters(AgentAdapters):
    async def ingest(self, video_id, context):
        context.check()
        return TranscriptResult(
            video_id=video_id,
            title=f"[FIXTURE] RAG {video_id}",
            channel_id="fixture-channel",
            published_at="2026-01-01",
            language="th",
            source="fixture",
            segments=[
                Segment(
                    segment_id="s1",
                    text="[FIXTURE] RAG retrieves evidence before answering.",
                    start_seconds=0,
                    duration_seconds=10,
                ),
                Segment(
                    segment_id="s2",
                    text="[FIXTURE] คำตอบต้องอ้างอิงหลักฐานจากวิดีโอ",
                    start_seconds=10,
                    duration_seconds=10,
                ),
            ],
        )


@pytest.fixture
async def integrated(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=True,
        session_cookie_secure=False,
        google_client_id="06-offline-client",
        adapter_mode="custom",
        adapter_factory="youtube_agent.integration:create_adapters",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        job_lease_seconds=60,
        job_retry_base_seconds=0,
    )
    db = Database(settings.database_url)
    upgrade_database(db)
    initialize(db)
    repo = Repository(db, settings)
    rag_settings = RagSettings(
        _env_file=None,
        embedding_provider="fixture",
        embedding_model="fixture-hash-v1",
        embedding_dimensions=64,
        chroma_persist_dir=tmp_path / "chroma",
        chunk_target_tokens=180,
        chunk_overlap_tokens=20,
    )
    model = LearningModel()
    adapters = OfflineAdapters(
        settings=settings,
        repository=repo,
        model=model,
        agent_settings=AgentSettings(_env_file=None),
        rag_settings=rag_settings,
        embedder=FixtureEmbedder(rag_settings),
    )
    worker = Worker(repo, adapters, settings)
    app = create_app(settings, db, adapters)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            owner = await login(client, app, "member-a")
            owned_repo = OwnedRepository(repo, owner["user_id"])
            for video in (VIDEO_A, VIDEO_B):
                imported = await client.post(
                    "/api/videos/import", json={"urls": [f"https://youtu.be/{video}"]}
                )
                assert imported.status_code == 202, imported.text
                job_id = imported.json()["jobs"][0]["job_id"]
                await worker.run_once(job_id)
                imported_job = owned_repo.get_job(job_id)
                assert imported_job["stage"] == "ready", imported_job
            yield SimpleNamespace(
                repo=owned_repo,
                raw_repo=repo,
                app=app,
                owner=owner,
                db=db,
                worker=worker,
                adapters=adapters,
                settings=settings,
                client=client,
                model=model,
            )
    finally:
        try:
            await adapters.close()
        finally:
            db.close()


async def test_http_research_artifacts_polling_and_reopened_database(integrated):
    env = integrated
    body = {"goal": "Learn RAG", "scope": {"video_ids": [VIDEO_A, VIDEO_B]}, "days": 7}
    response = await env.client.post(
        "/api/research", json=body, headers={"Idempotency-Key": "research-06"}
    )
    assert response.status_code == 202
    job_id = response.json()["run_id"]
    await env.worker.run_once(job_id)
    job = (await env.client.get(f"/api/jobs/{job_id}")).json()
    assert job["state"] == "completed", job
    result = job["result"]
    assert result["coverage"]["complete"]
    assert {c["video_id"] for c in result["citations"]} == {VIDEO_A, VIDEO_B}
    assert result["provider_metadata"]["provider"] == "fixture"
    artifact_id = result["artifact_ids"][0]
    artifact = (await env.client.get(f"/api/learning-artifacts/{artifact_id}")).json()
    assert len(artifact["content"]["days"]) == 7
    events = (await env.client.get(f"/api/research/{job_id}")).json()["events"]
    assert {e["tool_name"] for e in events} >= {"read_video_chunks", "create_learning_artifact"}
    replay = await env.client.post(
        "/api/research", json=body, headers={"Idempotency-Key": "research-06"}
    )
    assert replay.json()["run_id"] == job_id
    # A fresh DB engine and repository can read persisted results/events/artifacts.
    reopened = Database(env.settings.database_url)
    try:
        other = OwnedRepository(Repository(reopened, env.settings), env.owner["user_id"])
        assert other.get_job(job_id)["result"] == result
        assert other.artifact(artifact_id)["content"] == artifact["content"]
    finally:
        reopened.close()


async def test_all_direct_artifact_types_through_worker(integrated):
    env = integrated
    for kind in ("study_plan", "quiz", "flashcards"):
        response = await env.client.post(
            "/api/learning-artifacts",
            json={
                "type": kind,
                "scope": {"video_ids": [VIDEO_A]},
                "days": 3,
            },
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        await env.worker.run_once(job_id)
        job = env.repo.get_job(job_id)
        assert job["state"] == "completed", job
        artifact_id = job["result"]["artifact_ids"][0]
        artifact = (await env.client.get(f"/api/learning-artifacts/{artifact_id}")).json()
        assert artifact["type"] == kind
        assert all(c["video_id"] == VIDEO_A for c in artifact["citations"])
    assert not env.model.history  # Direct artifact requests need no research decision loop.


async def test_backend_generation_authorization_rejects_other_sources(integrated):
    env = integrated
    queued = env.repo.enqueue("research", {"goal": "Learn RAG", "scope": {"video_ids": [VIDEO_A]}})
    job = env.repo.claim(queued["job_id"])
    context = ExecutionContext(
        env.repo, job["job_id"], job["lease_token"], job["deadline_at"], env.settings
    )
    source = Source.model_validate(job["payload"]["sources"][0])
    source.video_id = VIDEO_B
    with pytest.raises(AppError) as caught:
        await env.adapters.research(
            {"goal": "RAG", "scope": {"video_ids": [VIDEO_B]}}, [source], context
        )
    assert caught.value.code == "invalid_scope"


async def test_running_cancellation_has_no_final_result(integrated):
    env = integrated
    started = asyncio.Event()

    async def waiting(history, timeout):
        started.set()
        await asyncio.sleep(0.03)
        # cancellation is rechecked immediately after the awaited call
        return ModelReply("read_video_chunks", {}, metadata())

    env.model.decide = waiting
    queued = env.repo.enqueue("research", {"goal": "Learn RAG", "scope": {"video_ids": [VIDEO_A]}})
    task = asyncio.create_task(env.worker.run_once(queued["job_id"]))
    await asyncio.wait_for(started.wait(), 10)
    cancelled = await env.client.post(f"/api/research/{queued['job_id']}/cancel")
    assert cancelled.status_code == 200
    await task
    result = env.repo.get_job(queued["job_id"])
    assert result["state"] == "cancelled"
    assert result["result"] is None


async def test_source_deletion_during_run_cannot_publish(integrated):
    env = integrated
    started = asyncio.Event()

    async def waiting(history, timeout):
        started.set()
        await asyncio.sleep(0.03)
        return ModelReply("read_video_chunks", {}, metadata())

    env.model.decide = waiting
    queued = env.repo.enqueue("research", {"goal": "Learn RAG", "scope": {"video_ids": [VIDEO_A]}})
    task = asyncio.create_task(env.worker.run_once(queued["job_id"]))
    await asyncio.wait_for(started.wait(), 10)
    deletion = await env.client.delete(f"/api/videos/{VIDEO_A}")
    assert deletion.status_code == 202
    await task
    result = env.repo.get_job(queued["job_id"])
    assert result["state"] in {"cancelled", "failed"}
    assert result["result"] is None


async def test_step_exhaustion_persists_honest_partial(integrated):
    env = integrated
    env.adapters.agent.settings.agent_max_steps = 1
    queued = env.repo.enqueue("research", {"goal": "Learn RAG", "scope": {"video_ids": [VIDEO_A]}})
    await env.worker.run_once(queued["job_id"])
    job = env.repo.get_job(queued["job_id"])
    assert job["state"] == "partial", job
    assert job["result"]["coverage"]["processed_chunks"] == 0
    assert job["result"]["citations"]


async def test_real_sdk_wire_through_backend_worker_and_chroma(integrated, monkeypatch):
    """The complete 02 -> 06 -> SDK HTTP mock -> 04 loop, not a scripted model gateway."""
    calls = []

    async def wire_broker(context, callback, **request):
        context.check()
        return await callback()

    # SDK wire test only. Actual durable project admission has a separate contract suite.
    monkeypatch.setattr(ExecutionContext, "gemini_call", wire_broker, raising=False)

    def handler(request):
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 100})
        body = json.loads(request.content)
        calls.append(body)
        decisions = sum("tools" in c for c in calls)
        if "tools" not in body:
            payload = json.loads(body["contents"][0]["parts"][0]["text"])
            cid = payload["untrusted_evidence"][0]["chunk_id"]
            parts = [
                {
                    "text": json.dumps(
                        {
                            "questions": [
                                {
                                    "question": "[FIXTURE] What does RAG retrieve?",
                                    "answer": "Evidence",
                                    "explanation": "The transcript describes evidence retrieval.",
                                    "citations": [cid],
                                }
                            ]
                        }
                    )
                }
            ]
        else:
            if decisions == 1:
                name, args = "read_video_chunks", {}
            elif decisions == 2:
                name, args = "create_learning_artifact", {"type": "quiz"}
            else:
                observation = next(
                    part["functionResponse"]["response"]
                    for content in body["contents"]
                    for part in content["parts"]
                    if "functionResponse" in part
                    and part["functionResponse"]["name"] == "read_video_chunks"
                )
                name, args = (
                    "finish_research",
                    {
                        "content": "[FIXTURE SDK WIRE] Evidence-based research result.",
                        "citation_ids": [e["chunk_id"] for e in observation["evidence"]],
                    },
                )
            parts = [
                {
                    "functionCall": {"name": name, "args": args, "id": f"call-{decisions}"},
                    "thoughtSignature": "c2lnbmF0dXJl",
                }
            ]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}
                ],
                "modelVersion": "fixture-http-mock",
                "usageMetadata": {"promptTokenCount": 50},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = genai.Client(
        api_key="test-only-secret",
        vertexai=False,
        http_options=types.HttpOptions(
            httpx_async_client=http, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    model = GeminiModel(AgentSettings(_env_file=None), client=client)
    integrated.adapters.agent.model = model
    try:
        queued = integrated.repo.enqueue(
            "research", {"goal": "Learn RAG", "scope": {"video_ids": [VIDEO_A]}}
        )
        await integrated.worker.run_once(queued["job_id"])
        job = integrated.repo.get_job(queued["job_id"])
        assert job["state"] == "completed", job
        assert job["result"]["artifacts"][0]["type"] == "quiz"
        assert job["result"]["provider_metadata"]["returned_model"] == "fixture-http-mock"
        assert len(calls) == 4  # Three decisions and one artifact generation.
    finally:
        await http.aclose()


async def test_two_member_research_events_artifacts_and_cancel(integrated):
    env = integrated
    scope = {"video_ids": [VIDEO_A]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as other:
        await login(other, env.app, "member-b")
        assert (
            await other.post("/api/research", json={"goal": "RAG", "scope": scope})
        ).status_code == 404
        response = await env.client.post("/api/research", json={"goal": "RAG", "scope": scope})
        job_id = response.json()["job_id"]
        assert (await other.get(f"/api/research/{job_id}")).status_code == 404
        assert (await other.post(f"/api/research/{job_id}/cancel")).status_code == 404
        await env.worker.run_once(job_id)
        result = env.repo.get_job(job_id)
        assert result["state"] == "completed", result
        artifact_id = result["result"]["artifact_ids"][0]
        assert (await other.get(f"/api/learning-artifacts/{artifact_id}")).status_code == 404
        assert (await env.client.get(f"/api/learning-artifacts/{artifact_id}")).status_code == 200


@pytest.mark.parametrize("kind", ["research", "artifact"])
async def test_backend_publication_fence_after_agent_returns(integrated, monkeypatch, kind):
    env = integrated
    request = {"scope": {"video_ids": [VIDEO_A]}}
    request.update({"goal": "Learn RAG"} if kind == "research" else {"type": "quiz"})
    job = env.repo.enqueue(kind, request)
    original = env.raw_repo.finish
    attempted = []

    def revoke_before_transaction(job_id, token, result=None, state="completed"):
        if job_id == job["job_id"]:
            assert result is not None  # The agent returned a valid candidate; publication is next.
            attempted.append(job_id)
            with env.db.write() as connection:
                connection.execute(
                    backend_db.user_videos.delete().where(
                        backend_db.user_videos.c.user_id == env.owner["user_id"],
                        backend_db.user_videos.c.video_id == VIDEO_A,
                    )
                )
        return original(job_id, token, result, state)

    monkeypatch.setattr(env.raw_repo, "finish", revoke_before_transaction)
    await env.worker.run_once(job["job_id"])
    stored = env.repo.get_job(job["job_id"])
    assert attempted == [job["job_id"]]
    assert stored["state"] in {"cancelled", "failed"} and stored["result"] is None
    with env.db.read() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(backend_db.artifacts)
                .where(backend_db.artifacts.c.job_id == job["job_id"])
            )
            == 0
        )
