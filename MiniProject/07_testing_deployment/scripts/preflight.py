"""Check effective configuration without contacting providers or opening data stores."""

import argparse
import json

from youtube_agent.config import AgentSettings
from youtube_answers.config import AnswerSettings
from youtube_answers.team import ENV_FILES
from youtube_backend.config import Settings
from youtube_ingestion.config import IngestionSettings
from youtube_rag.config import RagSettings


def inspect(require_key=False):
    backend = Settings()
    runtime = RagSettings(_env_file=ENV_FILES)
    maintenance = RagSettings()
    answers = AnswerSettings(_env_file=ENV_FILES)
    agent = AgentSettings(_env_file=ENV_FILES)
    IngestionSettings(_env_file=ENV_FILES)
    if (runtime.chroma_persist_dir, runtime.fingerprint) != (
        maintenance.chroma_persist_dir,
        maintenance.fingerprint,
    ):
        raise ValueError("Runtime and maintenance RAG configuration differ; export shared values")
    if backend.llm_model != answers.llm_model or answers.llm_model != agent.llm_model:
        raise ValueError("API, answers and agent must use the same explicit LLM_MODEL")
    if backend.adapter_factory != "youtube_answers.team:create_adapters":
        raise ValueError("Full deployment requires youtube_answers.team:create_adapters")
    if backend.backend_integration_profile != "live" or backend.adapter_mode != "custom":
        raise ValueError("Full team factory requires custom/live; use test doubles only in tests")
    if require_key and not all(
        s.gemini_api_key.get_secret_value() for s in (runtime, answers, agent)
    ):
        raise ValueError("Live team requires GEMINI_API_KEY")
    return dict(
        database_url=backend.database_url,
        chroma_persist_dir=str(runtime.chroma_persist_dir),
        embedding_model=runtime.embedding_model,
        fingerprint=runtime.fingerprint,
        llm_model=answers.llm_model,
        provider_access_verified=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-key", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    try:
        result = inspect(args.require_key)
        if args.initialize:
            from youtube_backend.database import Database
            from youtube_backend.migration import upgrade_database
            from youtube_backend.repository import Repository
            from youtube_rag.manifest import initialize

            settings = Settings()
            database = Database(settings.database_url)
            try:
                upgrade_database(database)
                Repository(database, settings).check_mode()
                initialize(database)
            finally:
                database.close()
        print(json.dumps(result, indent=2))
    except ValueError:
        parser.exit(
            1, "Configuration rejected; check shared database, index, model and key settings.\n"
        )


if __name__ == "__main__":
    main()
