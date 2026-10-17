import hashlib
import json
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from youtube_backend.config import PROJECT_ROOT


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "04_rag_knowledge" / ".env"),
        extra="ignore",
        env_file_encoding="utf-8",
    )
    embedding_provider: str = "gemini"
    embedding_model: str = "gemini-embedding-2"
    embedding_dimensions: int = Field(default=1536, ge=1, le=3072)
    embedding_tokenizer: str = "utf8-byte-budget-v1"
    gemini_api_key: SecretStr = SecretStr("")
    chroma_persist_dir: Path = Path("runtime/chroma")
    chunk_target_tokens: int = Field(default=600, ge=8, le=7000)
    chunk_overlap_tokens: int = Field(default=100, ge=0)
    retrieval_top_k: int = Field(default=8, ge=1, le=100)
    embedding_batch_size: int = Field(default=16, ge=1, le=64)
    rag_operation_timeout_seconds: float = Field(default=60, gt=0, le=600)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.chunk_overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("Chunk overlap must be smaller than the target")
        if self.embedding_provider not in {"gemini", "fixture"}:
            raise ValueError("Unsupported embedding provider")
        if self.embedding_tokenizer != "utf8-byte-budget-v1":
            raise ValueError("Use utf8-byte-budget-v1; Gemini counts are validated by the provider")
        if self.embedding_provider == "gemini":
            if self.embedding_model != "gemini-embedding-2":
                raise ValueError("This adapter supports gemini-embedding-2 only")
            if self.embedding_dimensions < 128:
                raise ValueError("Gemini embedding dimensions must be 128-3072")
        elif self.embedding_model != "fixture-hash-v1":
            raise ValueError("Fixture mode requires fixture-hash-v1")
        if not self.chroma_persist_dir.is_absolute():
            self.chroma_persist_dir = (PROJECT_ROOT / self.chroma_persist_dir).resolve()
        return self

    @property
    def fingerprint(self):
        # Includes chunking so a changed chunk layout cannot silently reuse an old index.
        config = {
            "schema": 2,
            "chunker": "segment-boundaries-utf8-v2",
            "provider": self.embedding_provider,
            "model": self.embedding_model,
            "dimensions": self.embedding_dimensions,
            "tokenizer": self.embedding_tokenizer,
            "target": self.chunk_target_tokens,
            "overlap": self.chunk_overlap_tokens,
            "distance": "cosine",
            "document_format": "title: {title} | text: {text}",
            "query_format": "task: search result | query: {text}",
            "provider_token_limit": 8192,
        }
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    @property
    def collection_name(self):
        return f"yk04_{self.fingerprint[:32]}"
