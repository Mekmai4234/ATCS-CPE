"""Use the backend's resolved runtime settings; never merge module dotenv files here.

yk-full exports all resolved fields before runtime or maintenance starts. Existing
backend Settings lacks some module-specific fields; those use process values/defaults,
with dotenv disabled. Shared fields always come from the supplied backend instance.
"""

from dataclasses import dataclass

from youtube_rag.config import RagSettings

from .config import AnswerSettings
from .models import error


def resolved_service(settings, cls):
    values = {name: getattr(settings, name) for name in cls.model_fields if hasattr(settings, name)}
    return cls(_env_file=None, **values)


@dataclass
class TeamConfiguration:
    answers: AnswerSettings
    rag: RagSettings
    ingestion: object
    agent: object


def load_team_configuration(settings):
    from youtube_agent.config import AgentSettings
    from youtube_ingestion.config import IngestionSettings

    if (
        settings.adapter_mode != "custom"
        or settings.adapter_factory != "youtube_answers.team:create_adapters"
        or settings.backend_integration_profile != "live"
    ):
        raise error(
            "integration_configuration", "Full team requires the live 05 team factory", status=503
        )
    result = TeamConfiguration(
        answers=resolved_service(settings, AnswerSettings),
        rag=resolved_service(settings, RagSettings),
        ingestion=resolved_service(settings, IngestionSettings),
        agent=resolved_service(settings, AgentSettings),
    )
    if result.rag.embedding_provider != "gemini":
        raise error("integration_configuration", "Live team requires Gemini embeddings", status=503)
    return result
