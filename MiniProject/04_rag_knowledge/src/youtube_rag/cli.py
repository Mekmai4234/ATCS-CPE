import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import sqlalchemy as sa
from youtube_backend import database as db
from youtube_backend.config import Settings
from youtube_backend.database import Database
from youtube_backend.errors import AppError
from youtube_backend.schemas import Segment, Source, TranscriptResult

from .config import RagSettings
from .embeddings import FixtureEmbedder, GeminiEmbedder
from .evaluation import evaluate
from .maintenance import MaintenanceExecution
from .manifest import Manifest, initialize
from .service import RagService


async def maintenance(args):
    settings = Settings()
    database = Database(settings.database_url)
    service = None
    try:
        if args.command == "init":
            initialize(database)
            return {"schema_version": 1, "initialized": True}
        if not args.workers_stopped:
            raise ValueError("Stop API/workers first and provide --workers-stopped")
        execution = MaintenanceExecution(database)
        execution.check()
        config = RagSettings()
        embedder = (
            FixtureEmbedder(config)
            if config.embedding_provider == "fixture"
            else GeminiEmbedder(config)
        )
        service = RagService(config, Manifest(database), embedder)
        if args.command == "gc":
            await service.cleanup(execution, include_staging=True)
            return {"garbage_collected": True}
        with database.read() as connection:
            video = (
                connection.execute(
                    sa.select(db.videos).where(db.videos.c.video_id == args.video_id)
                )
                .mappings()
                .one()
            )
            source = Source(
                video_id=video["video_id"],
                generation=video["generation"],
                transcript_version=video["transcript_version"],
            )
            record = (
                connection.execute(
                    sa.select(db.transcripts).where(
                        db.transcripts.c.video_id == source.video_id,
                        db.transcripts.c.version == source.transcript_version,
                    )
                )
                .mappings()
                .one()
            )
            segments = [
                Segment.model_validate(dict(row))
                for row in connection.execute(
                    sa.select(
                        db.segments.c.segment_id,
                        db.segments.c.text,
                        db.segments.c.start_seconds,
                        db.segments.c.duration_seconds,
                    )
                    .where(
                        db.segments.c.video_id == source.video_id,
                        db.segments.c.version == source.transcript_version,
                    )
                    .order_by(db.segments.c.position)
                ).mappings()
            ]
            transcript = TranscriptResult(
                video_id=source.video_id,
                title=video["title"],
                channel_id=video["channel_id"],
                channel_title=video["channel_title"],
                published_at=video["published_at"],
                language=record["language"],
                source=record["source"],
                segments=segments,
            )
        receipt = await service.index(source, transcript, execution, allow_reindex=True)
        return receipt.model_dump()
    finally:
        if service is not None:
            await service.close()
        database.close()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Module 04 knowledge management and evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Add module-04 schema to the initialized backend database")
    for name in ("gc", "reindex"):
        command = sub.add_parser(name)
        command.add_argument("--workers-stopped", action="store_true")
        if name == "reindex":
            command.add_argument("--video-id", required=True)
    demo = sub.add_parser("evaluate", help="Synthetic reference retrieval evaluation")
    demo.add_argument("--state", type=Path, help="New isolated state directory; default temporary")
    demo.add_argument("--phase", choices=["seed", "verify"], default="seed")
    demo.add_argument("--live", action="store_true", help="Explicitly call live Gemini embeddings")
    demo.add_argument("--dataset", type=Path)
    demo.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "evaluate":
            if args.state:
                result = asyncio.run(
                    evaluate(args.state, phase=args.phase, live=args.live, dataset=args.dataset)
                )
            else:
                if args.phase != "seed":
                    parser.error("--phase verify requires the previous --state directory")
                with tempfile.TemporaryDirectory(prefix="yk04-eval-") as path:
                    result = asyncio.run(evaluate(Path(path), live=args.live, dataset=args.dataset))
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        else:
            result = asyncio.run(maintenance(args))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except AppError as exc:
        print(
            json.dumps({"code": exc.code, "message": exc.message, "retryable": exc.retryable}),
            file=sys.stderr,
        )
        sys.exit(1)
    except (ValueError, RuntimeError, sa.exc.SQLAlchemyError):
        print(
            "Operation failed; verify arguments, database initialization and configuration.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
