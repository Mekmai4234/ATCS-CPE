from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from youtube_backend.config import PROJECT_ROOT


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "06_research_learning_agent" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        allow_inf_nan=False,
    )
    gemini_api_key: SecretStr = SecretStr("")
    llm_model: str = Field(default="gemini-3.5-flash", min_length=1, max_length=200)
    max_context_tokens: int = Field(default=24000, ge=1024, le=1000000)
    agent_max_steps: int = Field(default=8, ge=1, le=100)
    agent_timeout_seconds: float = Field(default=120, gt=0, le=3600)
    agent_finalize_reserve_seconds: float = Field(default=10, gt=0, le=120)
    agent_max_output_tokens: int = Field(default=2400, ge=128, le=32000)
    llm_timeout_seconds: float = Field(default=60, gt=0, le=600)
    agent_read_page_size: int = Field(default=30, ge=1, le=200)

    @model_validator(mode="after")
    def budgets(self):
        if self.agent_finalize_reserve_seconds >= self.agent_timeout_seconds:
            raise ValueError("Finalization reserve must be smaller than the run deadline")
        return self

    @classmethod
    def from_backend(cls, settings):
        """Consume already-resolved runtime settings instead of reloading module env files."""
        return cls(_env_file=None, **{name: getattr(settings, name) for name in cls.model_fields})
