from types import SimpleNamespace

from youtube_answers.config import AnswerSettings
from youtube_answers.reuse import reuse_configuration


def test_cache_separates_effective_configuration():
    settings = AnswerSettings(_env_file=None)
    rag = SimpleNamespace(fingerprint="index-a")
    original = reuse_configuration(settings, rag)
    for field, value in [
        ("answer_max_output_tokens", 512),
        ("retrieval_top_k", 2),
        ("max_context_tokens", 8192),
        ("vision_model", "other-model"),
    ]:
        assert reuse_configuration(settings.model_copy(update={field: value}), rag) != original
    assert reuse_configuration(settings, SimpleNamespace(fingerprint="index-b")) != original


def test_secret_does_not_change_configuration_identity():
    settings = AnswerSettings(_env_file=None, gemini_api_key="secret-one")
    other = AnswerSettings(_env_file=None, gemini_api_key="secret-two")
    rag = SimpleNamespace(fingerprint="index-a")
    assert reuse_configuration(settings, rag) == reuse_configuration(other, rag)
