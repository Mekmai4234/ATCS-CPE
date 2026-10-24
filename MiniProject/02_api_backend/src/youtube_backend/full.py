"""02-owned launcher for the unchanged 03–06 composition.

Only this entrypoint reads the full-system env file. Every resolved field is sent
to a child environment, so module-local dotenv files cannot override it.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import SettingsConfigDict
from sqlalchemy.engine import make_url

from .config import MODULE_ROOT, PROJECT_ROOT, Settings

FACTORY = "youtube_answers.team:create_adapters"


class FullSettings(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", allow_inf_nan=False)
    adapter_mode: str = "custom"
    backend_full_preflight: bool = True
    adapter_factory: str | None = FACTORY
    database_url: str = "sqlite:///./runtime/backend-full-live/app.db"
    chroma_persist_dir: str = "./runtime/backend-full-live/chroma"
    transcript_languages: str = "th,en"
    ingest_timeout_seconds: float = 30
    metadata_timeout_seconds: float = 5
    metadata_provider: str = "auto"
    youtube_api_key: SecretStr = SecretStr("")
    enable_transcription_fallback: bool = False
    answer_read_page_size: int = 100
    answer_max_chunks: int = 5000
    answer_max_model_calls: int = 64
    answer_max_history_messages: int = 12
    answer_max_history_bytes: int = 4000

    @model_validator(mode="after")
    def full_profile(self):
        if (
            self.adapter_mode != "custom"
            or not self.backend_full_preflight
            or self.adapter_factory != FACTORY
            or self.backend_integration_profile != "live"
            or self.embedding_provider != "gemini"
        ):
            raise ValueError(
                "Full launcher requires the live 05 team factory and Gemini embeddings"
            )
        path = Path(self.chroma_persist_dir).expanduser()
        self.chroma_persist_dir = str(
            (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
        )
        database_path = Path(make_url(self.database_url).database).resolve()
        chroma_path = Path(self.chroma_persist_dir)
        if database_path == chroma_path or chroma_path in database_path.parents:
            raise ValueError("SQLite must be outside the Chroma directory")
        return self

    def services(self):
        from youtube_agent.config import AgentSettings
        from youtube_answers.config import AnswerSettings
        from youtube_ingestion.config import IngestionSettings
        from youtube_rag.config import RagSettings

        result = {}
        for name, cls in (
            ("rag", RagSettings),
            ("answer", AnswerSettings),
            ("ingestion", IngestionSettings),
            ("agent", AgentSettings),
        ):
            # Fail when a new module field has not yet been added to this contract.
            values = {key: getattr(self, key) for key in cls.model_fields}
            result[name] = cls(_env_file=None, **values)
        return result

    def child_environment(self, inherited=None):
        environment = dict(os.environ if inherited is None else inherited)
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            elif isinstance(value, bool):
                value = str(value).lower()
            elif isinstance(value, (list, dict)):
                value = json.dumps(value)
            environment[name.upper()] = "" if value is None else str(value)
        environment["MINIPROJECT_ROOT"] = str(PROJECT_ROOT)
        return environment

    def summary(self):
        rag = self.services()["rag"]
        return {
            "database_url": self.database_url,
            "chroma_persist_dir": self.chroma_persist_dir,
            "profile": self.backend_integration_profile,
            "factory": self.adapter_factory,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "embedding_fingerprint": rag.fingerprint,
            "llm_model": self.llm_model,
            "gemini_key_configured": bool(self.gemini_api_key.get_secret_value()),
            "live_provider_verified": False,
            "authentication_required": self.auth_enabled,
            "google_login_configured": bool(self.google_client_id),
        }


def command_arguments(args):
    if args.command == "quota-policy":
        return [sys.executable, "-m", "youtube_backend.quota", "--workers-stopped"] + (
            ["--review-model-changes"] if args.review_model_changes else []
        )
    if args.command == "rag-init":
        # Additive 04 setup on an already verified pair, using this launcher's
        # resolved environment rather than independently selected module dotenvs.
        return [sys.executable, "-m", "youtube_rag.cli", "init", "--profile", "backend"]
    if args.command in {"migrate", "bootstrap-admin", "claim-legacy"}:
        command = [sys.executable, "-m", "youtube_backend.auth_cli", args.command]
        if args.command == "migrate":
            command += ["--workers-stopped", "--backup-dir", str(args.backup_dir)]
        elif args.command == "bootstrap-admin":
            command += ["--google-sub", args.google_sub]
        else:
            command += ["--admin-sub", args.admin_sub, "--owner-sub", args.owner_sub]
        return command
    if args.command in {"gc", "reindex"}:
        command = [sys.executable, "-m", "youtube_rag.cli", args.command, "--workers-stopped"]
        if args.command == "reindex":
            command += ["--video-id", args.video_id]
        return command
    return [sys.executable, "-m", "youtube_backend", args.command]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=MODULE_ROOT / "full" / ".env")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("config", "init", "check", "api", "worker"):
        commands.add_parser(name)
    rag_init = commands.add_parser("rag-init")
    rag_init.add_argument("--workers-stopped", action="store_true", required=True)
    quota_policy = commands.add_parser("quota-policy")
    quota_policy.add_argument("--workers-stopped", action="store_true", required=True)
    quota_policy.add_argument("--review-model-changes", action="store_true")
    migration = commands.add_parser("migrate")
    migration.add_argument("--workers-stopped", action="store_true", required=True)
    migration.add_argument("--backup-dir", type=Path, required=True)
    bootstrap = commands.add_parser("bootstrap-admin")
    bootstrap.add_argument("--google-sub", required=True)
    claim = commands.add_parser("claim-legacy")
    claim.add_argument("--admin-sub", required=True)
    claim.add_argument("--owner-sub", required=True)
    for name in ("gc", "reindex"):
        command = commands.add_parser(name)
        command.add_argument("--workers-stopped", required=True, action="store_true")
        if name == "reindex":
            command.add_argument("--video-id", required=True)
    args = parser.parse_args()
    hint = "Verify the selected env file and installed full-team packages."
    try:
        # A missing explicitly selected file is almost always a startup mistake.
        if args.env_file != MODULE_ROOT / "full" / ".env" and not args.env_file.is_file():
            raise ValueError("Configuration file is missing")
        settings = FullSettings(_env_file=args.env_file)
        settings.services()
        if args.command == "config":
            print(json.dumps(settings.summary(), indent=2))
            return
        from .full_pair import check_pair, initialize_pair

        if args.command == "init":
            hint = "Initialization requires a fresh pair, or an unchanged bound pair."
            initialize_pair(settings)
            print("Full-system SQLite/Chroma pair initialized; no provider requests made.")
            return
        hint = "Verify SQLite/Chroma binding and fingerprint with the same config used for init."
        if args.command != "migrate":
            check_pair(settings)
        if args.command == "check":
            print(json.dumps(dict(settings.summary(), pair_verified=True), indent=2))
            return
        if args.command in {"api", "worker"} and not settings.gemini_api_key.get_secret_value():
            parser.exit(2, "Full-system startup requires GEMINI_API_KEY in server configuration.\n")
        environment = settings.child_environment()
        arguments = command_arguments(args)
    except (Exception, KeyboardInterrupt):
        # ValidationError may contain the input key; never print raw exceptions.
        parser.exit(
            2,
            f"Full-system preflight failed. {hint} Use a new pair for legacy data.\n",
        )
    # POSIX exec preserves container signal/PID semantics. Windows waits for the child.
    if os.name != "nt":
        os.execve(sys.executable, arguments, environment)
    try:
        raise SystemExit(subprocess.call(arguments, env=environment))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
