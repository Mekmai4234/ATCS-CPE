import os
from types import SimpleNamespace

import pytest
from youtube_agent.config import AgentSettings
from youtube_backend.config import Settings
from youtube_backend.errors import AppError
from youtube_ingestion.config import IngestionSettings
from youtube_rag.config import RagSettings

from youtube_answers.config import AnswerSettings
from youtube_answers.configuration import load_team_configuration, resolved_service


def resolved(tmp_path):
    """Same union of service fields exported by 02's full launcher."""
    values = {}
    for cls in (Settings, RagSettings, AnswerSettings, AgentSettings, IngestionSettings):
        values.update(cls(_env_file=None).model_dump())
    values.update(
        adapter_mode="custom",
        adapter_factory="youtube_answers.team:create_adapters",
        backend_integration_profile="live",
        database_url=f"sqlite:///{tmp_path / 'selected.db'}",
        chroma_persist_dir=tmp_path / "selected-chroma",
        llm_model="selected-model",
        embedding_provider="gemini",
        embedding_model="gemini-embedding-2",
        embedding_dimensions=256,
        retrieval_top_k=3,
        answer_max_model_calls=9,
    )
    return SimpleNamespace(**values)


def test_factory_shared_fields_follow_resolved_backend_not_stale_process(tmp_path, monkeypatch):
    settings = resolved(tmp_path)
    monkeypatch.setenv("LLM_MODEL", "stale-model")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "wrong-store"))
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    services = load_team_configuration(settings)
    assert services.answers.llm_model == services.agent.llm_model == "selected-model"
    assert services.rag.chroma_persist_dir == tmp_path / "selected-chroma"
    assert services.rag.embedding_dimensions == 256
    assert services.answers.answer_max_model_calls == 9


def test_factory_does_not_read_module_dotenv_files(tmp_path, monkeypatch):
    settings = resolved(tmp_path)
    for cls in (AnswerSettings, RagSettings, AgentSettings, IngestionSettings):
        path = tmp_path / (cls.__name__ + ".env")
        path.write_text("LLM_MODEL=hostile\nEMBEDDING_PROVIDER=openai\n", encoding="utf-8")
        monkeypatch.setitem(cls.model_config, "env_file", path)
    services = load_team_configuration(settings)
    assert services.rag.embedding_provider == "gemini"
    assert services.answers.llm_model == services.agent.llm_model == "selected-model"


def test_legacy_backend_module_specific_fields_use_only_process_and_defaults(tmp_path, monkeypatch):
    backend = Settings(
        _env_file=None,
        adapter_mode="custom",
        adapter_factory="youtube_answers.team:create_adapters",
    )
    path = tmp_path / "05.env"
    path.write_text("ANSWER_MAX_MODEL_CALLS=99\n", encoding="utf-8")
    monkeypatch.setitem(AnswerSettings.model_config, "env_file", path)
    monkeypatch.setenv("ANSWER_MAX_MODEL_CALLS", "7")
    assert resolved_service(backend, AnswerSettings).answer_max_model_calls == 7
    monkeypatch.delenv("ANSWER_MAX_MODEL_CALLS")
    assert resolved_service(backend, AnswerSettings).answer_max_model_calls == 64


def test_exported_runtime_and_maintenance_resolve_identical_storage_and_fingerprint(
    tmp_path, monkeypatch
):
    settings = resolved(tmp_path)
    for name, value in vars(settings).items():
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        monkeypatch.setenv(name.upper(), str(value))
    # As yk-full does, export every resolved field. Hostile local file values lose.
    path = tmp_path / "maintenance.env"
    path.write_text(
        "DATABASE_URL=sqlite:///wrong.db\nCHROMA_PERSIST_DIR=wrong\nEMBEDDING_DIMENSIONS=768\n",
        encoding="utf-8",
    )
    maintenance_backend = Settings(_env_file=path)
    maintenance_rag = RagSettings(_env_file=path)
    runtime = load_team_configuration(maintenance_backend)
    assert runtime.rag.chroma_persist_dir == maintenance_rag.chroma_persist_dir
    assert runtime.rag.fingerprint == maintenance_rag.fingerprint
    assert maintenance_backend.database_url.endswith("selected.db")
    assert os.environ["DATABASE_URL"] == settings.database_url


@pytest.mark.parametrize(
    "change",
    [
        {"adapter_factory": "youtube_backend.team:create_adapters"},
        {"adapter_mode": "fixture"},
        {"backend_integration_profile": "offline"},
        {"embedding_provider": "fixture", "embedding_model": "fixture-hash-v1"},
    ],
)
def test_full_factory_rejects_a_different_profile_or_factory(tmp_path, change):
    settings = resolved(tmp_path)
    for key, value in change.items():
        setattr(settings, key, value)
    with pytest.raises(AppError) as caught:
        load_team_configuration(settings)
    assert caught.value.code == "integration_configuration"
