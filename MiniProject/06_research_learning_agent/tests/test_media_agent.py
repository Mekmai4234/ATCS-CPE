import time
from types import SimpleNamespace

import pytest
from conftest import VIDEO_A, Context, ScriptedModel, metadata
from youtube_backend.errors import AppError
from youtube_backend.evidence_v2 import SourceSnapshotV2

from youtube_agent.config import AgentSettings
from youtube_agent.media import MediaAgentService, MediaRecord
from youtube_agent.models import ModelReply


def record(kind="ocr", frame="b"):
    return MediaRecord.model_validate(
        {
            "evidence_id": f"{kind}-{frame}",
            "citation": {
                "source": {
                    "video_id": VIDEO_A,
                    "generation": 1,
                    "kind": kind,
                    "evidence_version": "a" * 64,
                },
                "frame_id": frame * 64,
                "asset_id": "c" * 64,
                "start_seconds": 2,
                "text": "[FIXTURE OCR] RAG on a classroom slide",
                "asset_url": "/api/media/assets/" + "c" * 64,
            },
        }
    )


class Tools:
    def __init__(self):
        self.active = True
        self.records = [record()]
        self.calls = []

    def authorize(self, sources, context):
        context.check()
        if not self.active:
            raise AppError("member_access_denied", "Revoked", 403)
        return "server-owner-and-source-snapshot"

    async def inventory(self, sources, context):
        self.calls.append("inventory")
        return [{"kind": "ocr", "prepared_evidence_complete": True}]

    async def search(self, question, sources, context):
        self.calls.append("search")
        return [r.model_dump() for r in self.records]

    async def evidence(self, sources, ids, context):
        self.calls.append("evidence")
        return [r.model_dump() for r in self.records if r.evidence_id in ids]

    async def frames(self, sources, context):
        return ["d" * 64]


class Planner(ScriptedModel):
    async def decide(self, history, timeout, **kwargs):
        return await super().decide(history, timeout)


def service(actions=None, **limits):
    tools, ctx = Tools(), Context()
    ctx.end = time.monotonic() + 120
    model = Planner(actions) if actions is not None else None
    agent = MediaAgentService(AgentSettings(_env_file=None, **limits), tools, planner=model)
    return SimpleNamespace(
        agent=agent, tools=tools, context=ctx, model=model, sources=[record().citation.source]
    )


async def test_local_only_without_transcript_or_model_has_real_frame_citations():
    env = service()
    result = await env.agent.research({"goal": "RAG"}, env.sources, env.context)
    assert result["state"] == "partial" and result["reason"] == "quota_pending"
    assert result["model_calls"] == 0 and not result["visual_coverage"]["whole_video_reviewed"]
    citation = result["citations"][0]["citation"]
    assert citation["source"]["kind"] == "ocr" and citation["start_seconds"] == 2
    assert "transcript_version" not in citation["source"]
    assert env.tools.calls == ["inventory", "search", "evidence"]


async def test_stored_frame_is_reused_without_vision_request():
    env = service(
        [
            ("inspect_frame", {"frame_id": "b" * 64}),
            (
                "finish_research",
                {"content": "Stored visual says RAG", "citation_ids": ["visual-b"]},
            ),
        ]
    )
    env.tools.records = [record("visual")]
    env.sources = [env.tools.records[0].citation.source]
    result = await env.agent.research({"goal": "RAG"}, env.sources, env.context)
    assert result["state"] == "completed" and result["model_calls"] == 2
    assert result["visual_coverage"]["additional_frame_count"] == 0
    assert env.model.history[1][-1]["data"]["final_only"] is False


async def test_ocr_does_not_count_as_an_existing_visual_description():
    env = service(
        [
            ("inspect_frame", {"frame_id": "b" * 64}),
            ("finish_research", {"content": "Visual description", "citation_ids": ["visual-b"]}),
        ]
    )
    env.sources.append(record("visual").citation.source)

    async def frames(*args):
        return ["b" * 64]

    env.tools.frames = frames
    calls = []

    async def observe(frame, sources, context):
        calls.append(frame)
        result = record("visual")
        env.tools.records.append(result)
        return [result.model_dump()]

    env.agent.vision = SimpleNamespace(observe=observe)
    result = await env.agent.research({"goal": "RAG"}, env.sources, env.context)
    assert calls == ["b" * 64] and result["state"] == "completed"
    assert result["visual_coverage"]["additional_frame_count"] == 1


@pytest.mark.parametrize(
    "code", ["quota_wait", "free_tier_unverified", "provider_rate_limited", "provider_unavailable"]
)
async def test_shared_quota_failure_returns_checked_stored_partial_without_retry(code):
    env = service([AppError(code, "Not available", 503)])
    result = await env.agent.research({"goal": "RAG"}, env.sources, env.context)
    assert result["state"] == "partial" and result["reason"] == code
    assert len(env.model.history) == 1
    assert result["citations"]


async def test_foreign_or_made_up_frame_never_reaches_05():
    env = service([("inspect_frame", {"frame_id": "e" * 64})])
    with pytest.raises(AppError) as exc:
        await env.agent.research({"goal": "RAG"}, env.sources, env.context)
    assert exc.value.code == "invalid_scope"


async def test_model_budget_preserves_final_answer_no_more_expansion():
    env = service(
        [("search_prepared_media", {"query": "first"}), ("inspect_frame", {"frame_id": "d" * 64})],
        agent_max_model_calls=2,
    )
    result = await env.agent.research({"goal": "RAG"}, env.sources, env.context)
    assert result["state"] == "partial" and result["model_calls"] == 2
    assert result["visual_coverage"]["additional_frame_count"] == 0


async def test_revocation_during_decision_never_exports_cached_evidence():
    env = service([])

    async def revoke(*args, **kwargs):
        env.tools.active = False
        return ModelReply(
            "finish_research", {"content": "Hidden", "citation_ids": ["ocr-b"]}, metadata()
        )

    env.model.decide = revoke
    with pytest.raises(AppError):
        await env.agent.research({"goal": "RAG"}, env.sources, env.context)


async def test_artifact_cannot_invent_new_citation_ids():
    env = service([("finish_research", {"content": "Quiz", "citation_ids": ["ocr-b"]})])

    async def generate(*args, **kwargs):
        return SimpleNamespace(
            content={"cards": [{"front": "Question", "back": "Answer", "citations": ["made-up"]}]}
        )

    env.model.generate = generate
    with pytest.raises(AppError) as exc:
        await env.agent.research(
            {"goal": "RAG", "artifact_type": "flashcards"}, env.sources, env.context
        )
    assert exc.value.code == "invalid_citation"


@pytest.mark.parametrize("kind", ["quiz", "flashcards", "study_plan"])
async def test_learning_outputs_keep_the_exact_ocr_version(kind):
    env = service([("finish_research", {"content": "Learning", "citation_ids": ["ocr-b"]})])

    async def generate(request, records, schema, timeout, **kwargs):
        assert kwargs["citation_key"] == "evidence_id"
        content = {
            "quiz": {
                "questions": [
                    {
                        "question": "RAG?",
                        "answer": "Evidence",
                        "explanation": "OCR",
                        "citations": ["ocr-b"],
                    }
                ]
            },
            "flashcards": {
                "cards": [{"front": "RAG?", "back": "Evidence", "citations": ["ocr-b"]}]
            },
            "study_plan": {
                "days": [
                    {"day": n, "topic": "OCR RAG", "citations": ["ocr-b"]} for n in range(1, 3)
                ]
            },
        }[kind]
        return SimpleNamespace(content=schema.model_validate(content))

    env.model.generate = generate
    result = await env.agent.research(
        {"goal": "RAG", "artifact_type": kind, "days": 2}, env.sources, env.context
    )
    assert result["state"] == "completed" and result["artifact"]
    assert result["citations"][0]["citation"]["source"] == env.sources[0].model_dump()


async def test_repeated_frame_never_repeats_05_generation():
    env = service([("inspect_frame", {"frame_id": "d" * 64})] * 2)
    env.sources.append(record("visual", "d").citation.source)
    calls = []

    async def observe(frame, sources, context):
        calls.append(frame)
        value = record("visual", "d")
        env.tools.records.append(value)
        return [value.model_dump()]

    env.agent.vision = SimpleNamespace(observe=observe)
    result = await env.agent.research({"goal": "RAG"}, env.sources, env.context)
    assert calls == ["d" * 64]
    assert result["state"] == "partial" and result["visual_coverage"]["additional_frame_count"] == 1


async def test_native_02_04_image_only_lexical_path(tmp_path):
    import hashlib

    import sqlalchemy as sa
    from youtube_backend import database as db
    from youtube_backend.auth import actor_id
    from youtube_backend.config import Settings
    from youtube_backend.database import Database
    from youtube_backend.evidence_v2 import MediaEnrichment
    from youtube_backend.integrations import ExecutionContext
    from youtube_backend.media import MediaStore
    from youtube_backend.migration import upgrade_database
    from youtube_backend.repository import Repository
    from youtube_rag.config import RagSettings
    from youtube_rag.embeddings import FixtureEmbedder
    from youtube_rag.manifest import BackendExecution, initialize

    from youtube_agent.integration import AgentAdapters

    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=True,
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        media_asset_dir=str(tmp_path / "assets"),
    )
    database = Database(settings.database_url)
    adapters = None
    try:
        upgrade_database(database)
        initialize(database)
        with database.write() as c:
            c.execute(
                db.users.insert().values(
                    user_id="a",
                    google_sub="fixture-a",
                    role="user",
                    status="active",
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )
        repo = Repository(database, settings)
        token = actor_id.set("a")
        try:
            imported = repo.import_urls([f"https://youtu.be/{VIDEO_A}"])[0]
            repo.cancel(imported["job_id"])
            queued = MediaStore(repo).enqueue(VIDEO_A)
            job = repo.claim(queued["job_id"])
        finally:
            actor_id.reset(token)
        context = ExecutionContext(
            repo, job["job_id"], job["lease_token"], job["deadline_at"], settings
        )
        summary = MediaStore(repo).publish(
            context,
            MediaEnrichment(
                sampling_version="fixture",
                ocr_version="fixture",
                prompt_version="local",
                source_sha256=hashlib.sha256(b"fixture").hexdigest(),
                duration_seconds=10,
                frames=[
                    dict(
                        timestamp_seconds=2,
                        content=b"\x89PNG\r\n\x1a\nfixture",
                        mime="image/png",
                        ocr_text="RAG classroom slide",
                    )
                ],
            ),
        )
        source = SourceSnapshotV2.model_validate(summary["snapshots"][0])
        config = AgentSettings(_env_file=None)
        rag_config = RagSettings(
            _env_file=None,
            embedding_provider="fixture",
            embedding_model="fixture-hash-v1",
            embedding_dimensions=64,
            chroma_persist_dir=tmp_path / "chroma",
        )
        adapters = AgentAdapters(
            settings=settings,
            repository=repo,
            model=ScriptedModel(),
            agent_settings=config,
            rag_settings=rag_config,
            embedder=FixtureEmbedder(rag_config),
        )
        await adapters.rag.media.index(source, BackendExecution(context), semantic=False)
        result = await adapters.research_media({"goal": "RAG"}, [source], context)
        assert result["citations"][0]["citation"]["source"]["kind"] == "ocr"
        assert result["model_calls"] == 0
        with database.read() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(db.transcripts)) == 0
    finally:
        if adapters:
            await adapters.close()
        database.close()
