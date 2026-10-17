import sys

from . import cli

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"api", "worker", "db"}:
        raise SystemExit("Usage: python -m youtube_backend {api|worker|db} [arguments]")
    command = sys.argv.pop(1)
    {"api": cli.api, "worker": cli.worker, "db": cli.migrate}[command]()
