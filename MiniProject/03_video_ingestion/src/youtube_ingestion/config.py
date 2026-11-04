import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from youtube_backend.config import PROJECT_ROOT


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "03_video_ingestion" / ".env"),
        extra="ignore",
        env_file_encoding="utf-8",
        # Validation errors must not echo proxy credentials or API keys.
        hide_input_in_errors=True,
    )
    transcript_languages: str = "th,en"
    ingest_timeout_seconds: float = Field(default=30, gt=0, le=300)
    metadata_timeout_seconds: float = Field(default=5, gt=0, le=30)
    metadata_provider: Literal["auto", "oembed", "youtube_api", "none"] = "auto"
    youtube_api_key: SecretStr = SecretStr("")
    enable_transcription_fallback: bool = False
    # Optional caption proxy for hosts whose IP YouTube blocks (cloud/VPS ranges).
    # Either one generic http(s) proxy URL, or Webshare rotating residential credentials.
    youtube_proxy_url: SecretStr = SecretStr("")
    youtube_webshare_username: str = ""
    youtube_webshare_password: SecretStr = SecretStr("")

    @property
    def caption_proxy(self):
        """Proxy request for the caption subprocess; None means a direct connection."""
        url = self.youtube_proxy_url.get_secret_value()
        if url:
            return {"kind": "generic", "url": url}
        if self.youtube_webshare_username:
            return {
                "kind": "webshare",
                "username": self.youtube_webshare_username,
                "password": self.youtube_webshare_password.get_secret_value(),
            }
        return None

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
        url = self.youtube_proxy_url.get_secret_value()
        webshare = self.youtube_webshare_username, self.youtube_webshare_password.get_secret_value()
        if url and any(webshare):
            raise ValueError("Set YOUTUBE_PROXY_URL or YOUTUBE_WEBSHARE_*, not both")
        if any(webshare) and not all(webshare):
            raise ValueError("Webshare proxy requires username and password")
        if url:
            # Never echo the URL: it usually embeds credentials.
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError("YOUTUBE_PROXY_URL must be http(s)://[user:pass@]host:port")
        return self


class MediaSettings(BaseSettings):
    """Opt-in local preparation; separate from 02 FullSettings' caption fields."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "03_video_ingestion" / ".env"),
        env_prefix="MEDIA_",
        extra="ignore",
    )
    enabled: bool = False
    upload_root: Path = PROJECT_ROOT / "runtime" / "uploads"
    work_root: Path = PROJECT_ROOT / "runtime" / "media03"
    ffprobe: str = "ffprobe"
    ffmpeg: str = "ffmpeg"
    tesseract: str = "tesseract"
    tessdata_dir: Path | None = None
    ocr_languages: str = "tha+eng"
    max_input_bytes: int = Field(default=256 * 1024 * 1024, ge=1024, le=1024**3)
    max_duration_seconds: float = Field(default=600, gt=0, le=600)
    max_pixels: int = Field(default=3840 * 2160, ge=1024, le=3840 * 2160)
    max_frames: int = Field(default=12, ge=1, le=12)
    sample_interval_seconds: float = Field(default=60, gt=0, le=600)
    near_duplicate_distance: int = Field(default=2, ge=0, le=8)
    max_frame_bytes: int = Field(default=16 * 1024 * 1024, ge=1024, le=32 * 1024 * 1024)
    tool_timeout_seconds: float = Field(default=30, gt=0, le=120)
    total_timeout_seconds: float = Field(default=300, gt=0, le=600)
    memory_mb: int = Field(default=1024, ge=128, le=4096)
    cpu_seconds: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def validate_media(self):
        if not re.fullmatch(r"[a-z]{3}(?:\+[a-z]{3}){0,3}", self.ocr_languages):
            raise ValueError("MEDIA_OCR_LANGUAGES must be local Tesseract language codes")
        uploads, work = self.upload_root.resolve(), self.work_root.resolve()
        if uploads.is_relative_to(work) or work.is_relative_to(uploads):
            raise ValueError("Upload and private work roots must be disjoint")
        return self
