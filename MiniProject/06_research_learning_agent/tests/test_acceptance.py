"""06 acceptance: shared runtime configuration, source integrity and frontend events."""

import pytest
from conftest import VIDEO_A, VIDEO_B, BranchModel, ScriptedModel, evidence
from youtube_backend.config import Settings
from youtube_backend.errors import AppError
from youtube_backend.schemas import Source

from youtube_agent.config import AgentSettings


async def test_finalization_rechecks_changed_source(unit):
    unit.service.model = BranchModel()
    original = unit.knowledge.evidence

    async def changed(*args):
        records = await original(*args)
        return [e.model_copy(update={"text": "Changed after model call"}) for e in records]

    unit.knowledge.evidence = changed
    with pytest.raises(AppError) as caught:
        await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert caught.value.code in {"invalid_evidence", "source_changed"}
    assert not any(
        e.tool_name == "run_controller" and e.state == "completed" for e in unit.ctx.events
    )


@pytest.mark.parametrize("kind", ["research", "artifact"])
async def test_missing_citations_during_finalization_fail(unit, kind):
    async def missing(*args):
        return []

    unit.knowledge.evidence = missing
    with pytest.raises(AppError) as caught:
        if kind == "research":
            unit.service.model = BranchModel()
            await unit.service.research(unit.request, unit.sources, unit.ctx)
        else:
            await unit.service.artifact(
                {"type": "quiz", "scope": {"video_ids": [VIDEO_A]}}, unit.sources, unit.ctx
            )
    assert caught.value.code == "source_changed"


async def test_index_inventory_change_cannot_be_published(unit):
    calls = 0

    async def inventory(*args):
        nonlocal calls
        calls += 1
        return 2 if calls == 1 else 3

    unit.knowledge.inventory = inventory
    unit.service.model = BranchModel()
    with pytest.raises(AppError) as caught:
        await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert caught.value.code == "source_changed"


@pytest.mark.parametrize("code", ["incomplete_index", "index_configuration_mismatch"])
async def test_store_failures_are_not_disguised_as_partial_success(unit, code):
    unit.model.actions = [("read_video_chunks", {}), AppError(code, "Safe source error", 503)]
    with pytest.raises(AppError) as caught:
        await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert caught.value.code == code


@pytest.mark.parametrize("operation", ["research", "artifact"])
async def test_request_cannot_name_different_source_set(unit, operation):
    with pytest.raises(AppError) as caught:
        if operation == "research":
            await unit.service.research(
                {"goal": "RAG", "scope": {"video_ids": [VIDEO_B]}}, unit.sources, unit.ctx
            )
        else:
            await unit.service.artifact(
                {"type": "quiz", "scope": {"video_ids": [VIDEO_B]}}, unit.sources, unit.ctx
            )
    assert caught.value.code == "invalid_scope"
    assert not unit.model.history and not unit.model.generated


async def test_resolved_filter_may_narrow_original_video_selection(unit):
    unit.request["scope"]["video_ids"].append(VIDEO_B)
    unit.service.model = BranchModel()
    result = await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert result.coverage.expected_videos == 1
    assert all(c.video_id == VIDEO_A for c in result.citations)


async def test_tool_subset_is_checked_even_with_broken_knowledge_adapter(unit):
    unit.sources.append(Source(video_id=VIDEO_B, generation=1, transcript_version="v1"))
    unit.request["scope"]["video_ids"].append(VIDEO_B)
    unit.knowledge.records.append(evidence(video=VIDEO_B, cid="chunk-b"))
    # Both videos belong to the run, but the read tool requested only A.
    unit.knowledge.selected = lambda sources: unit.knowledge.records
    unit.model.actions = [("read_video_chunks", {"video_ids": [VIDEO_A]})]
    with pytest.raises(AppError) as caught:
        await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert caught.value.code == "invalid_evidence"


@pytest.mark.parametrize("complete", [True, False])
async def test_terminal_events_are_ordered_and_match_actual_result(unit, complete):
    if complete:
        unit.service.model = BranchModel()
    else:
        unit.config.agent_max_steps = 1
        unit.model.actions = [("read_video_chunks", {})]
    result = await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert [e.step for e in unit.ctx.events] == sorted(e.step for e in unit.ctx.events)
    assert unit.ctx.events[-1].tool_name == "run_controller"
    assert unit.ctx.events[-1].state == result.state
    assert f"complete={result.coverage.complete}" in unit.ctx.events[-1].summary


async def test_direct_artifact_emits_safe_progress(unit):
    await unit.service.artifact(
        {"type": "flashcards", "scope": {"video_ids": [VIDEO_A]}}, unit.sources, unit.ctx
    )
    assert unit.ctx.events[0].state == "running"
    assert unit.ctx.events[-1].state == "completed"
    assert "[FIXTURE]" not in str(unit.ctx.events)  # No transcript/private reasoning in logs.


def test_resolved_backend_settings_ignore_later_module_env(monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_model="resolved-model",
        agent_max_steps=4,
        agent_timeout_seconds=40,
        agent_finalize_reserve_seconds=6,
    )
    monkeypatch.setenv("LLM_MODEL", "different-module-model")
    config = AgentSettings.from_backend(settings)
    assert config.llm_model == "resolved-model"
    assert config.agent_max_steps == 4
    assert config.agent_finalize_reserve_seconds == 6


async def test_factory_closes_model_when_rag_setup_fails(monkeypatch):
    from youtube_agent import integration

    gateway = ScriptedModel()
    monkeypatch.setattr(integration, "create_model", lambda config: gateway)

    def fail(**kwargs):
        raise RuntimeError("setup failure")

    monkeypatch.setattr(integration, "AgentAdapters", fail)
    with pytest.raises(RuntimeError, match="setup failure"):
        await integration.create_adapters(settings=Settings(_env_file=None), repository=None)
    assert gateway.closed
