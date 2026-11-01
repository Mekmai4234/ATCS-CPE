from types import SimpleNamespace

import pytest
from youtube_backend.errors import AppError

from youtube_rag.config import RagSettings
from youtube_rag.embeddings import OllamaEmbedder, create_embedder


def config(**extra):
    return RagSettings(
        _env_file=None,
        embedding_provider="ollama",
        embedding_model="fixture:embed",
        local_embedding_model="fixture:embed",
        local_embedding_digest="a" * 64,
        embedding_dimensions=3,
        **extra,
    )


def execution(settings, response):
    seen = []

    async def invoke(**request):
        seen.append(request)
        return response

    return SimpleNamespace(
        check=lambda: None,
        context=SimpleNamespace(settings=settings),
        local_inference=invoke,
        seen=seen,
    )


def test_local_index_namespace_includes_provider_model_dimension_and_digest():
    baseline = config()
    for update in (
        {"local_embedding_digest": "b" * 64},
        {"embedding_dimensions": 4},
        {"embedding_model": "other", "local_embedding_model": "other"},
    ):
        changed = RagSettings(_env_file=None, **dict(baseline.model_dump(), **update))
        assert changed.collection_name != baseline.collection_name
    assert isinstance(create_embedder(baseline), OllamaEmbedder)


async def test_local_embed_preserves_thai_and_rejects_truncation_at_transport_boundary():
    settings = config()
    run = execution(settings, {"embeddings": [[1.0, 2.0, 3.0]]})
    vectors = await OllamaEmbedder(settings).embed(["ทดสอบภาษาไทย"], 1, execution=run)
    assert vectors == [[1.0, 2.0, 3.0]]
    request = run.seen[0]
    assert request["operation"] == "embed"
    assert request["digest"] == "a" * 64
    assert "ทดสอบภาษาไทย" in request["payload"]["input"][0]
    assert "truncate" not in request["payload"]  # 02 owns truncate=False.


@pytest.mark.parametrize("vectors", [[[1.0, 2.0]], [[0, 0, 0]], [[1, float("nan"), 3]], []])
async def test_local_vectors_fail_closed_on_bad_shape_and_values(vectors):
    settings = config()
    with pytest.raises(AppError) as caught:
        await OllamaEmbedder(settings).embed(
            ["ข้อมูล"], 1, execution=execution(settings, {"embeddings": vectors})
        )
    assert caught.value.code == "invalid_embedding"


async def test_local_cannot_run_without_broker_or_with_changed_identity():
    settings = config()
    embedder = OllamaEmbedder(settings)
    with pytest.raises(AppError) as caught:
        await embedder.embed(["ข้อมูล"], 1)
    assert caught.value.code == "local_broker_required"
    other = config().model_copy(update={"local_embedding_digest": "b" * 64})
    run = execution(other, {"embeddings": [[1, 2, 3]]})
    with pytest.raises(AppError) as caught:
        await embedder.embed(["ข้อมูล"], 1, execution=run)
    assert caught.value.code == "index_configuration_mismatch"
    assert run.seen == []
