import pytest
from youtube_backend.errors import AppError


async def test_final_model_slot_does_not_start_another_tool(unit):
    unit.config.agent_max_model_calls = 2
    unit.model.actions = [("read_video_chunks", {}), ("create_learning_artifact", {"type": "quiz"})]
    result = await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert result.state == "partial" and not unit.model.generated
    assert len(unit.model.history) == 2 and len(unit.knowledge.calls) == 1


async def test_tool_budget_leaves_room_to_validate_partial(unit):
    unit.config.agent_max_tool_calls = 3
    unit.model.actions = [("read_video_chunks", {})]
    result = await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert result.state == "partial" and not result.coverage.complete
    assert not unit.knowledge.calls and not result.citations


@pytest.mark.parametrize("code", ["quota_wait", "provider_rate_limited", "provider_unavailable"])
async def test_quota_stops_expansion_without_model_retry(unit, code):
    unit.model.actions = [("read_video_chunks", {}), AppError(code, "Quota or provider wait", 503)]
    result = await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert result.state == "partial" and code in result.content
    assert len(unit.model.history) == 2 and result.citations


async def test_wait_before_evidence_propagates_to_backend(unit):
    unit.model.actions = [AppError("quota_wait", "Wait", 503)]
    with pytest.raises(AppError) as exc:
        await unit.service.research(unit.request, unit.sources, unit.ctx)
    assert exc.value.code == "quota_wait"
