"""04-owned maintenance configuration, matching the selected runtime factory."""

from pathlib import Path

from youtube_backend.config import PROJECT_ROOT, Settings

from .config import RagSettings

TEAM05_ENV_FILES = tuple(
    PROJECT_ROOT / name
    for name in (
        ".env",
        "04_rag_knowledge/.env",
        "03_video_ingestion/.env",
        "06_research_learning_agent/.env",
        "05_ai_answers_analysis/.env",
    )
)
INGESTION03_ENV_FILES = TEAM05_ENV_FILES[:3]


def load_configuration(*, profile="auto", env_files=None):
    files = None
    if env_files:
        files = tuple(Path(path).expanduser().resolve() for path in env_files)
        if any(not path.is_file() for path in files):
            raise ValueError("Every explicit env file must exist")
    backend = Settings(**({"_env_file": files} if files else {}))
    if profile == "auto":
        profile = {
            "youtube_answers.team:create_adapters": "team05",
            "youtube_backend.team:create_adapters": "backend",
            "youtube_ingestion.integration:create_adapters": "ingestion03",
        }.get(backend.adapter_factory, "module04")
    if profile == "backend":
        values = {name: getattr(backend, name) for name in RagSettings.model_fields}
        if backend.backend_integration_profile == "offline":
            values.update(
                embedding_provider="fixture",
                embedding_model="fixture-hash-v1",
                embedding_dimensions=64,
            )
        rag = RagSettings(_env_file=None, **values)
    elif files:
        rag = RagSettings(_env_file=files)
    elif profile == "team05":
        # Mirrors the existing 05 factory without importing its generation clients.
        rag = RagSettings(_env_file=TEAM05_ENV_FILES)
    elif profile == "ingestion03":
        rag = RagSettings(_env_file=INGESTION03_ENV_FILES)
    else:
        rag = RagSettings()
    return backend, rag, profile


def describe_configuration(backend, rag, profile):
    # Allowlist only: never serialize BaseSettings or provider secrets into diagnostics.
    return {
        "profile": profile,
        "database_url": backend.database_url,
        "chroma_persist_dir": str(rag.chroma_persist_dir.resolve()),
        "embedding_provider": rag.embedding_provider,
        "embedding_model": rag.embedding_model,
        "embedding_dimensions": rag.embedding_dimensions,
        "index_configuration": rag.fingerprint,
        "collection": rag.collection_name,
    }
