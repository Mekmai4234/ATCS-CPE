import json

import pytest
from conftest import Context
from youtube_backend.errors import AppError, LeaseLost

from youtube_agent.config import AgentSettings
from youtube_agent.local import LocalModel, create_model
from youtube_agent.models import FinishArgs


def settings(**changes):
    return AgentSettings(
        _env_file=None,
        generation_provider="ollama",
        local_model="fixture:tiny",
        local_model_digest="a" * 64,
        local_context_tokens=8192,
        **changes,
    )


class LocalContext(Context):
    def __init__(self):
        super().__init__()
        self.saved, self.calls = {}, []
        self.result = {"content": "ข้อสรุปจากหลักฐาน", "citation_ids": ["chunk-1"]}

    def checkpoint(self, key, value=None):
        self.check()
        if value is not None:
            self.saved[key] = value
        return self.saved.get(key)

    async def local_inference(self, **request):
        self.calls.append(request)
        return {"message": {"content": json.dumps(self.result, ensure_ascii=False)}}


async def test_structured_checkpoint_skips_generation_after_restart_and_pins_full_input():
    ctx = LocalContext()
    model = create_model(settings())
    first = await model._structured({"task": "สรุป"}, FinishArgs, 1, ctx)
    restarted = LocalModel(settings())
    cached = await restarted._structured({"task": "สรุป"}, FinishArgs, 1, ctx)
    assert first.content == cached.content and len(ctx.calls) == 1
    assert first.metadata.provider == "ollama"
    assert cached.metadata.provider == "ollama-cache"
    assert "@sha256:" in first.metadata.returned_model
    await restarted._structured({"task": "เปรียบเทียบ"}, FinishArgs, 1, ctx)
    assert len(ctx.calls) == 2
    ctx.cancelled = True
    with pytest.raises(LeaseLost):
        await restarted._structured({"task": "สรุป"}, FinishArgs, 1, ctx)


async def test_deterministic_research_reads_then_generates_without_tool_calling(unit):
    ctx = LocalContext()
    unit.service.model = LocalModel(settings())
    result = await unit.service.research(unit.request, unit.sources, ctx)
    assert result.state == "completed"
    assert result.coverage.complete
    assert result.provider_metadata.provider == "ollama"
    assert len(ctx.calls) == 1
    assert [call[0] for call in unit.knowledge.calls] == ["read"]


async def test_local_context_limit_and_invalid_json_fail_without_repair_calls():
    ctx = LocalContext()
    model = LocalModel(settings())
    with pytest.raises(AppError) as caught:
        await model._structured({"task": "ไทย" * 10000}, FinishArgs, 1, ctx)
    assert caught.value.code == "context_budget_exceeded" and not ctx.calls
    ctx.result = {"unexpected": True}
    with pytest.raises(AppError) as caught:
        await model._structured({"task": "สรุป"}, FinishArgs, 1, ctx)
    assert caught.value.code == "invalid_model_output"
    assert len(ctx.calls) == 1 and not ctx.saved


async def test_local_does_not_publish_unknown_citations(unit):
    ctx = LocalContext()
    ctx.result["citation_ids"] = ["invented"]
    unit.service.model = LocalModel(settings())
    result = await unit.service.research(unit.request, unit.sources, ctx)
    assert result.state == "partial"
    assert all(c.chunk_id != "invented" for c in result.citations)


async def test_empty_corpus_yields_no_model_call(unit):
    ctx = LocalContext()
    unit.knowledge.records = []
    unit.service.model = LocalModel(settings())
    with pytest.raises(AppError):
        await unit.service.research(unit.request, unit.sources, ctx)
    assert not ctx.calls


@pytest.mark.parametrize("kind", ["quiz", "flashcards", "study_plan"])
async def test_learning_checkpoint_reuses_generated_result_and_revalidates_input(unit, kind):
    ctx = LocalContext()
    request = {
        "type": kind,
        "topic": "Learn RAG",
        "scope": {"video_ids": [unit.sources[0].video_id]},
        "days": 2,
    }
    first = await unit.service.artifact(request, unit.sources, ctx)
    second = await unit.service.artifact(request, unit.sources, ctx)
    assert first.content == second.content and len(unit.model.generated) == 1
    assert second.provider_metadata.provider == "fixture-cache"
    assert second.provider_metadata.usage == {}
    unit.knowledge.records[0] = unit.knowledge.records[0].model_copy(
        update={"text": "New evidence"}
    )
    await unit.service.artifact(request, unit.sources, ctx)
    assert len(unit.model.generated) == 2


async def test_local_schema_constrains_citations_to_supplied_ids():
    ctx = LocalContext()
    await LocalModel(settings())._structured(
        {"untrusted_evidence": [{"chunk_id": "chunk-1"}]}, FinishArgs, 1, ctx
    )
    shape = ctx.calls[0]["payload"]["format"]
    assert shape["properties"]["citation_ids"]["items"]["enum"] == ["chunk-1"]
