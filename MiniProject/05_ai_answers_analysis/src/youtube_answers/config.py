from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from youtube_backend.config import PROJECT_ROOT


class AnswerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "05_ai_answers_analysis" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        allow_inf_nan=False,
    )
    gemini_api_key: SecretStr = SecretStr("")
    llm_model: str = Field(default="gemini-3.5-flash", min_length=1, max_length=200)
    llm_timeout_seconds: float = Field(default=60, gt=0, le=600)
    max_context_tokens: int = Field(default=24000, ge=4096, le=1000000)
    answer_max_output_tokens: int = Field(default=1200, ge=128, le=32000)
    enable_streaming: bool = False
    retrieval_top_k: int = Field(default=8, ge=1, le=100)
    answer_read_page_size: int = Field(default=100, ge=1, le=200)
    answer_max_chunks: int = Field(default=5000, ge=1, le=100000)
    answer_max_model_calls: int = Field(default=64, ge=1, le=1000)
    answer_max_history_messages: int = Field(default=12, ge=0, le=40)
    answer_max_history_bytes: int = Field(default=4000, ge=0, le=20000)

    def model_post_init(self, context):
        if self.enable_streaming:
            raise ValueError("Streaming is not implemented; use validated JSON results")
