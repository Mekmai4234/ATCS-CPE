import re
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from youtube_backend.config import PROJECT_ROOT


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "03_video_ingestion" / ".env"),
        extra="ignore",
        env_file_encoding="utf-8",
    )
    transcript_languages: str = "th,en"
    ingest_timeout_seconds: float = Field(default=30, gt=0, le=300)
    metadata_timeout_seconds: float = Field(default=5, gt=0, le=30)
    metadata_provider: Literal["auto", "oembed", "youtube_api", "none"] = "auto"
    youtube_api_key: SecretStr = SecretStr("")
    enable_transcription_fallback: bool = False

    @property
    def languages(self):
        return list(dict.fromkeys(x.strip() for x in self.transcript_languages.split(",")))

    @model_validator(mode="after")
    def supported_configuration(self):
        if not 1 <= len(self.languages) <= 20 or any(
            not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", x) for x in self.languages
        ):
            raise ValueError("TRANSCRIPT_LANGUAGES requires 1-20 comma-separated language codes")
        if self.enable_transcription_fallback:
            raise ValueError("Speech-to-text fallback is not implemented; keep it disabled")
        if self.metadata_provider == "youtube_api" and not self.youtube_api_key.get_secret_value():
            raise ValueError("YouTube Data API metadata requires YOUTUBE_API_KEY")
        return self
