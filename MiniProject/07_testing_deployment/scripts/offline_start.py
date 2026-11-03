"""TEST ONLY startup for internal-network container drills; never a release command."""

import argparse
import os
import sys

from preflight import inspect_settings, resolve
from youtube_backend.full_pair import check_pair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["api", "worker"])
    args = parser.parse_args()
    settings = resolve()
    if settings.gemini_api_key.get_secret_value() != "fixture07-no-provider-requests":
        parser.exit(2, "Offline drill requires its synthetic key, never a real credential.\n")
    inspect_settings(settings, require_key=True)
    check_pair(settings)
    # This deliberately cannot accept real credentials or release evidence. Its
    # compose profiles require internal:true and submit no generation/import jobs.
    environment = settings.child_environment()
    command = [sys.executable, "-m", "youtube_backend", args.service]
    os.execve(sys.executable, command, environment)


if __name__ == "__main__":
    main()
