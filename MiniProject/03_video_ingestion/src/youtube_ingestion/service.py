import asyncio
import logging

from youtube_backend.errors import AppError
from youtube_backend.integrations import ExecutionContext
from youtube_backend.schemas import TranscriptResult
from youtube_backend.urls import VIDEO_ID, normalize_url

from .captions import SubprocessCaptions, remote_error
from .config import IngestionSettings
from .errors import failure
from .metadata import YouTubeMetadata
from .models import Metadata
from .normalize import normalize

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, settings=None, *, captions=None, metadata=None):
        self.settings = settings or IngestionSettings()
        self.captions = captions if captions is not None else SubprocessCaptions()
        self.metadata = metadata if metadata is not None else YouTubeMetadata(self.settings)
        self.closed = False

    async def ingest(self, video_id: str, context: ExecutionContext) -> TranscriptResult:
        context.check()
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            raise failure("invalid_video_id", "Provide a valid YouTube video ID", 422)
        if self.closed:
            raise failure("ingest_unavailable", "Ingestion adapter is closed", 503)
        timeout = min(self.settings.ingest_timeout_seconds, context.remaining_seconds)
        task = None
        try:
            async with asyncio.timeout(timeout):
                # Metadata has a small separate budget; failure must not discard usable captions.
                metadata_timeout = min(self.settings.metadata_timeout_seconds, timeout / 4)
                try:
                    async with asyncio.timeout(metadata_timeout):
                        metadata = await self.metadata.fetch(video_id, metadata_timeout)
                except (AppError, TimeoutError):
                    logger.warning("ingestion_metadata_unavailable video_id=%s", video_id)
                    metadata = Metadata()
                context.check()
                task = asyncio.create_task(
                    self.captions.fetch(video_id, self.settings.languages, timeout)
                )
                while not task.done():
                    await asyncio.wait({task}, timeout=0.1)
                    context.check()
                track = await task
                context.check()
                result = normalize(video_id, track, metadata)
                context.check()
                return result
        except TimeoutError:
            raise remote_error("ingest_timeout") from None
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    async def ingest_url(self, url, context):
        return await self.ingest(normalize_url(url), context)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            await self.captions.close()
        finally:
            await self.metadata.close()
