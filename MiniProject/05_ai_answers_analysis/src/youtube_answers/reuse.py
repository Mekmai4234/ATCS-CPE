"""Version answer reuse by effective generation, retrieval and prompt configuration."""

from youtube_backend.repository import digest

from .prompts import POLICY, PROMPT_VERSION
from .question_scope import RETRIEVAL_VERSION


def reuse_configuration(settings, rag_settings):
    # Credential material never belongs in a cache key or report.
    return digest(
        [
            settings.model_dump(mode="json", exclude={"gemini_api_key"}),
            rag_settings.fingerprint,
            PROMPT_VERSION,
            POLICY,
            RETRIEVAL_VERSION,
        ]
    )
