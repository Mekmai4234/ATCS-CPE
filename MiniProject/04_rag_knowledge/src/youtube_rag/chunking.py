import asyncio
from dataclasses import dataclass

from youtube_backend.schemas import Source, TranscriptResult

from .config import RagSettings
from .errors import error
from .models import Chunk, digest


@dataclass
class Piece:
    text: str
    segment_id: str
    start: float
    end: float


class Chunker:
    def __init__(self, settings: RagSettings):
        self.settings = settings

    def count(self, text):
        # Offline chunk budget, NOT a Gemini tokenizer or billable token measurement.
        # Final prepared content is counted with Gemini before every live embedding.
        return len(text.encode("utf-8"))

    def _split(self, text):
        # Split at Unicode character boundaries; decoding arbitrary token slices can corrupt Thai.
        target = self.settings.chunk_target_tokens
        offset = 0
        while offset < len(text):
            # Bound each operation even for a malformed caption containing a huge segment.
            candidate = text[offset : offset + target]
            if self.count(candidate) <= target:
                yield candidate
                offset += len(candidate)
                continue
            low, high = 1, len(candidate)
            while low < high:
                mid = (low + high + 1) // 2
                if self.count(candidate[:mid]) <= target:
                    low = mid
                else:
                    high = mid - 1
            yield candidate[:low]
            offset += low

    def build(self, source: Source, transcript: TranscriptResult):
        return list(self._assemble(source, transcript, list(self._pieces(source, transcript))))

    async def build_async(self, source, transcript, check):
        pieces, result = [], []
        for piece in self._pieces(source, transcript):
            check()
            pieces.append(piece)
            await asyncio.sleep(0)
        for chunk in self._assemble(source, transcript, pieces):
            check()
            result.append(chunk)
            await asyncio.sleep(0)
        return result

    def _pieces(self, source, transcript):
        if transcript.video_id != source.video_id or not source.transcript_version:
            raise error("invalid_transcript", "Transcript does not match the supplied source")
        for segment in transcript.segments:
            if not segment.text.strip():
                raise error("invalid_transcript", "Transcript contains an empty segment")
            for text in self._split(segment.text):
                yield Piece(
                    text,
                    segment.segment_id,
                    segment.start_seconds,
                    segment.start_seconds + segment.duration_seconds,
                )

    def _assemble(self, source, transcript, pieces):
        start, ordinal = 0, 0
        while start < len(pieces):
            end = start + 1
            while end < len(pieces):
                text = "\n".join(p.text for p in pieces[start : end + 1])
                if self.count(text) > self.settings.chunk_target_tokens:
                    break
                end += 1
            group = pieces[start:end]
            text = "\n".join(p.text for p in group)
            yield Chunk(
                chunk_id=digest([source.model_dump(), self.settings.fingerprint, ordinal, text]),
                video_id=source.video_id,
                generation=source.generation,
                transcript_version=source.transcript_version,
                embedding_version=self.settings.fingerprint,
                title=transcript.title or f"YouTube {source.video_id}",
                text=text,
                segment_ids=list(dict.fromkeys(p.segment_id for p in group)),
                ordinal=ordinal,
                token_count=self.count(text),
                start_seconds=min(p.start for p in group),
                end_seconds=max(p.end for p in group),
                canonical_url=f"https://www.youtube.com/watch?v={source.video_id}",
            )
            ordinal += 1
            if end == len(pieces):
                break
            # Whole-piece overlap is a maximum, rather than splitting caption boundaries.
            next_start = end
            while next_start > start + 1:
                candidate = "\n".join(p.text for p in pieces[next_start - 1 : end])
                if self.count(candidate) > self.settings.chunk_overlap_tokens:
                    break
                next_start -= 1
            start = next_start
