import json

import pytest
from conftest import Context, evidence
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
    with pytest.raises(AppError) as caught:
        await unit.service.research(unit.request, unit.sources, ctx)
    assert caught.value.code == "invalid_citation"


async def test_empty_corpus_yields_no_model_call(unit):
    ctx = LocalContext()
    unit.knowledge.records = []
    unit.service.model = LocalModel(settings())
    with pytest.raises(AppError):
        await unit.service.research(unit.request, unit.sources, ctx)
    assert not ctx.calls


@pytest.mark.parametrize(
    "failure", ["local_unavailable", "local_timeout", "local_busy", "quota_wait"]
)
async def test_synthesis_failure_returns_revalidated_excerpts_without_analysis_credit(
    unit, failure
):
    ctx = LocalContext()
    unit.service.model = LocalModel(settings())

    async def unavailable(**request):
        raise AppError(failure, "sensitive transport details", 503, True)

    ctx.local_inference = unavailable
    result = await unit.service.research(unit.request, unit.sources, ctx)
    assert result.state == "partial" and result.citations
    assert "Retrieved source excerpts" in result.content and failure in result.content
    assert "sensitive" not in result.content
    assert result.coverage.processed_chunks == 0 and not result.coverage.complete
    assert result.provider_metadata.provider == "none"


async def test_synthesis_failure_cannot_hide_evidence_change_or_cancellation(unit):
    ctx = LocalContext()
    unit.service.model = LocalModel(settings())

    async def changed(**request):
        unit.knowledge.records.clear()
        raise AppError("local_unavailable", "Unavailable", 503, True)

    ctx.local_inference = changed
    with pytest.raises(AppError, match="no longer available"):
        await unit.service.research(unit.request, unit.sources, ctx)


async def test_synthesis_failure_after_cancel_never_publishes_partial(unit):
    ctx = LocalContext()
    unit.service.model = LocalModel(settings())

    async def cancelled(**request):
        ctx.cancelled = True
        raise AppError("local_unavailable", "Unavailable", 503, True)

    ctx.local_inference = cancelled
    with pytest.raises(LeaseLost):
        await unit.service.research(unit.request, unit.sources, ctx)


async def test_local_research_restart_reuses_successful_synthesis_and_revalidates(unit):
    ctx = LocalContext()
    unit.service.model = LocalModel(settings())
    first = await unit.service.research(unit.request, unit.sources, ctx)
    unit.service.model = LocalModel(settings())
    resumed = await unit.service.research(unit.request, unit.sources, ctx)
    assert len(ctx.calls) == 1 and first.content == resumed.content
    assert resumed.provider_metadata.provider == "ollama-cache"
    assert resumed.coverage.complete


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


async def test_explicit_fresh_generation_skips_structured_checkpoint():
    ctx = LocalContext()
    model = LocalModel(settings())
    await model._structured({"task": "สรุป"}, FinishArgs, 1, ctx)
    ctx.cache_bypass = True
    fresh = await model._structured({"task": "สรุป"}, FinishArgs, 1, ctx)
    assert len(ctx.calls) == 2
    assert fresh.metadata.provider == "ollama"
    resumed = await model._structured({"task": "สรุป"}, FinishArgs, 1, ctx)
    assert len(ctx.calls) == 2
    assert resumed.metadata.provider == "ollama-cache"


async def test_long_research_uses_relevant_tail_candidates_when_bounded(unit):
    from types import SimpleNamespace

    unit.knowledge.records = [evidence(cid=f"chunk-{i}", text="Basics") for i in range(74)]
    unit.knowledge.records[-1] = evidence(
        cid="chunk-73", text="Kubernetes reconciles desired state."
    )

    async def select(question, sources, execution, **options):
        assert question == "Explain Kubernetes"
        values = [unit.knowledge.records[-1], *unit.knowledge.records[:8]]
        return {
            "items": [SimpleNamespace(evidence=lambda record=record: record) for record in values],
            "retrieved_chunks": len(values),
            "inspected_chunks": 74,
            "indexed_chunks": 74,
        }

    unit.knowledge.rag = SimpleNamespace(select_context=select)
    config = settings().model_copy(update={"local_context_tokens": 32768})
    unit.service.settings = config
    unit.service.model = LocalModel(config)
    ctx = LocalContext()
    ctx.result["citation_ids"] = ["chunk-73"]
    request = dict(unit.request, goal="Explain Kubernetes")
    result = await unit.service.research(request, unit.sources, ctx)
    supplied = json.loads(ctx.calls[0]["payload"]["messages"][-1]["content"])["untrusted_evidence"]
    assert supplied[0]["chunk_id"] == "chunk-73"
    assert result.state == "partial" and result.coverage.processed_chunks == 9
    assert result.provider_metadata.usage["indexed_chunks"] == 74
    assert result.provider_metadata.usage["supplied_chunks"] == 9
    assert len(ctx.calls) == 1


@pytest.mark.parametrize(
    "count,window,complete", [(32, 32768, True), (74, 32768, False), (32, 4096, False)]
)
async def test_multi_page_research_reserves_synthesis_with_default_call_and_step_budgets(
    unit, count, window, complete
):
    unit.knowledge.records = [
        evidence(cid=f"chunk-{i}", text="RAG uses evidence.") for i in range(count)
    ]
    config = settings().model_copy(update={"local_context_tokens": window})
    unit.service.settings = config
    unit.service.model = LocalModel(config)
    ctx = LocalContext()
    ctx.result["citation_ids"] = ["chunk-0"]
    result = await unit.service.research(unit.request, unit.sources, ctx)
    assert len(ctx.calls) == 1
    assert result.coverage.complete is complete
    assert result.state == ("completed" if complete else "partial")
    supplied = json.loads(ctx.calls[0]["payload"]["messages"][-1]["content"])["untrusted_evidence"]
    assert result.coverage.processed_chunks == len(supplied)
    assert result.coverage.expected_chunks == count
    assert "model_calls=1" in ctx.events[-1].summary
    if complete:
        assert len(supplied) == count
        assert len(unit.knowledge.calls) == 4
    else:
        assert 0 < len(supplied) < count
        assert any("bounded subset" in note for note in result.coverage.notes)
