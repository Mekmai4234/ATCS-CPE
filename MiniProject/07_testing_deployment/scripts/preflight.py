"""Resolve one full-system snapshot for preflight, initialization and both services."""

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from youtube_backend.full import FullSettings
from youtube_backend.full_pair import check_pair, initialize_pair
from youtube_rag.configuration import TEAM05_ENV_FILES, load_configuration


@contextmanager
def exported(settings):
    values = settings.child_environment({})
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resolve(env_file=None):
    if env_file is not None:
        env_file = Path(env_file).expanduser().resolve()
        if not env_file.is_file():
            raise ValueError("Selected environment file must exist")
    return FullSettings(_env_file=env_file)


def inspect_settings(settings, require_key=False):
    services = settings.services()
    with exported(settings):
        try:
            from youtube_answers.configuration import load_team_configuration
        except ModuleNotFoundError as exc:
            if exc.name != "youtube_answers.configuration":
                raise
            # develop before PR13: the legacy factory reads these dotenv files.
            # Export every FullSettings field first, so its actual service loaders
            # still consume the SAME snapshot; never import the removed ENV_FILES.
            runtime = {
                name: type(value)(_env_file=TEAM05_ENV_FILES) for name, value in services.items()
            }
        else:
            team = load_team_configuration(settings)
            runtime = dict(
                rag=team.rag, answer=team.answers, agent=team.agent, ingestion=team.ingestion
            )
        backend, maintenance, profile = load_configuration(profile="auto")
    if backend.database_url != settings.database_url:
        raise ValueError("Runtime and maintenance SQLite settings differ")
    if (runtime["rag"].chroma_persist_dir, runtime["rag"].fingerprint) != (
        maintenance.chroma_persist_dir,
        maintenance.fingerprint,
    ):
        raise ValueError("Runtime and maintenance vector settings differ")
    for name, value in runtime.items():
        if value.model_dump() != services[name].model_dump():
            raise ValueError("Runtime differs from the selected full-system snapshot")
    if require_key and not settings.gemini_api_key.get_secret_value():
        raise ValueError("Live startup requires GEMINI_API_KEY")
    summary = settings.summary()
    summary.update(
        maintenance_profile=profile,
        fingerprint=maintenance.fingerprint,
        provider_access_verified=False,
    )
    return summary


def inspect(require_key=False, env_file=None):
    return inspect_settings(resolve(env_file), require_key)


def main():
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--require-key", action="store_true")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--initialize", action="store_true")
    action.add_argument("--run", choices=["api", "worker"])
    args = parser.parse_args()
    try:
        settings = resolve(args.env_file)
        result = inspect_settings(settings, args.require_key or bool(args.run))
        if args.initialize:
            initialize_pair(settings)
            result["pair_verified"] = True
        if args.run:
            check_pair(settings)
    except Exception:
        # Pydantic validation errors may embed secret input values.
        parser.exit(1, "Configuration/pair rejected; check the selected full-system settings.\n")
    if not args.run:
        print(json.dumps(result, indent=2))
        return
    arguments = [sys.executable, "-m", "youtube_backend", args.run]
    environment = settings.child_environment()
    if os.name != "nt":
        os.execve(sys.executable, arguments, environment)
    try:
        raise SystemExit(__import__("subprocess").call(arguments, env=environment))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
