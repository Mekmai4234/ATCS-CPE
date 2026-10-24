import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def find_project_root():
    configured = os.environ.get("MINIPROJECT_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not root.is_dir():
            raise RuntimeError("MINIPROJECT_ROOT must be an existing directory")
        return root
    for start in (Path(__file__).resolve().parent, Path.cwd()):
        for candidate in (start, *start.parents):
            if (candidate / ".env.example").is_file() and (
                candidate / "02_api_backend" / "pyproject.toml"
            ).is_file():
                return candidate
    raise RuntimeError("Cannot locate MiniProject root; set MINIPROJECT_ROOT explicitly")


PROJECT_ROOT = find_project_root()
MODULE_ROOT = PROJECT_ROOT / "02_api_backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", MODULE_ROOT / "integration" / ".env"),
        extra="ignore",
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    auth_enabled: bool = True
    gemini_free_policy_file: str | None = None
    gemini_max_concurrent: int = Field(default=1, ge=1, le=20)
    gemini_user_concurrent: int = Field(default=1, ge=1, le=10)
    media_asset_dir: str = "./runtime/media-assets"
    media_max_frames: int = Field(default=12, ge=1, le=100)
    media_max_frame_bytes: int = Field(default=2_000_000, ge=1024, le=20_000_000)
    google_client_id: str = ""
    session_ttl_seconds: int = Field(default=86400, ge=300, le=2592000)
    session_cookie_secure: bool = True
    auth_trusted_origins: list[str] = []
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_origin: str = "http://localhost:3000"
    database_url: str = "sqlite:///./runtime/app.db"
    adapter_mode: str = "unavailable"
    adapter_factory: str | None = None
    backend_integration_profile: Literal["live", "offline"] = "live"
    backend_full_preflight: bool = False
    enable_streaming: bool = False
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_lease_seconds: float = Field(default=30, ge=0.3, le=600)
    job_timeout_seconds: float = Field(default=180, gt=0, le=3600)
    job_retry_base_seconds: float = Field(default=2, ge=0, le=300)
    worker_poll_seconds: float = Field(default=1, gt=0, le=60)
    import_max_urls: int = Field(default=50, ge=1, le=500)
    llm_model: str = "gemini-3.5-flash"
    gemini_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=60, gt=0)
    agent_timeout_seconds: float = Field(default=120, gt=0)
    agent_max_steps: int = Field(default=8, ge=1, le=100)
    max_context_tokens: int = Field(default=24000, gt=0)
    answer_max_output_tokens: int = Field(default=1200, gt=0)
    agent_max_output_tokens: int = Field(default=2400, gt=0)
    agent_finalize_reserve_seconds: float = Field(default=10, gt=0, le=120)
    agent_read_page_size: int = Field(default=30, ge=1, le=200)
    embedding_provider: str = "gemini"
    embedding_model: str = "gemini-embedding-2"
    embedding_dimensions: int = Field(default=1536, ge=8, le=3072)
    embedding_tokenizer: str = "utf8-byte-budget-v1"
    chroma_persist_dir: str = "./runtime/chroma"
    chunk_target_tokens: int = Field(default=600, ge=8, le=7000)
    chunk_overlap_tokens: int = Field(default=100, ge=0)
    retrieval_top_k: int = Field(default=8, ge=1, le=100)
    embedding_batch_size: int = Field(default=16, ge=1, le=64)
    rag_operation_timeout_seconds: float = Field(default=60, gt=0, le=600)

    @model_validator(mode="after")
    def supported_configuration(self):
        from urllib.parse import urlsplit

        origins = self.auth_trusted_origins or [self.web_origin]
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username
                or "*" in origin
                or origin.endswith("/")
            ):
                raise ValueError("Trusted origins must be exact origins without trailing slash")
        if self.app_env not in {"development", "test"} and (
            not self.auth_enabled
            or not self.session_cookie_secure
            or any(not origin.startswith("https://") for origin in origins)
        ):
            raise ValueError("Production requires authentication, HTTPS origins and Secure cookies")
        if self.adapter_mode not in {"unavailable", "fixture", "custom"}:
            raise ValueError("ADAPTER_MODE must be unavailable, fixture, or custom")
        if self.adapter_mode == "custom" and not self.adapter_factory:
            raise ValueError("Custom mode requires ADAPTER_FACTORY=package.module:factory")
        if self.adapter_mode == "fixture" and self.app_env not in {"development", "test"}:
            raise ValueError("Fixture mode is restricted to development/test")
        if self.backend_integration_profile == "offline" and self.app_env not in {
            "development",
            "test",
        }:
            raise ValueError("Offline integration is restricted to development/test")
        if self.enable_streaming:
            raise ValueError("Streaming is not implemented; use ENABLE_STREAMING=false")
        url = make_url(self.database_url)
        if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
            raise ValueError("This prototype requires a file-backed sqlite:/// database")
        if not Path(url.database).is_absolute():
            url = url.set(database=str((PROJECT_ROOT / url.database).resolve()))
        self.database_url = url.render_as_string(hide_password=False)
        return self
