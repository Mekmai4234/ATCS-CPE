import time
from types import SimpleNamespace

import pytest
from youtube_backend.schemas import Evidence, ProviderMetadata, Source
from youtube_rag.models import Chunk, ChunkPage, CoverageInventory, SearchHit

from youtube_answers.config import AnswerSettings
from youtube_answers.models import Generated, GeneratedAnswer
from youtube_answers.service import AnswerService

VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "jNQXAC9IVRw"


def source(video=VIDEO_A):
    return Source(video_id=video, generation=1, transcript_version="v1")


def chunk(i=0, video=VIDEO_A, text=None):
    return Chunk(
        chunk_id=f"{video}-{i}",
        video_id=video,
        transcript_version="v1",
        title=f"[FIXTURE] {video}",
        text=text or "RAG retrieves evidence before answering.",
        start_seconds=i * 10,
        end_seconds=i * 10 + 10,
        generation=1,
        embedding_version="fixture",
        segment_ids=[f"s{i}"],
        ordinal=i,
        token_count=50,
        canonical_url=f"https://www.youtube.com/watch?v={video}",
    )


def metadata():
    return ProviderMetadata(
        provider="fixture",
        requested_model="fixture",
        returned_model="fixture-v1",
        usage={"prompt_token_count": 10},
        latency_ms=1,
    )


class Context:
    def __init__(self):
        self.deadline = time.monotonic() + 120
        self.failure = None

    def check(self):
        if self.failure:
            raise self.failure

    @property
    def remaining_seconds(self):
        return max(0, self.deadline - time.monotonic())


class ScriptedModel:
    def __init__(self):
        self.payloads = []
        self.output = None
        self.closed = False

    async def generate(self, data, timeout):
        self.payloads.append(data)
        if self.output is not None:
            return Generated(self.output, metadata())
        # Labelled fixture retains one statement per input and unions refs when merging.
        items = data["untrusted_evidence"]
        refs = list(dict.fromkeys(c for n in items for c in n["citation_ids"]))
        return Generated(
            GeneratedAnswer.model_validate(
                {
                    "status": "answered",
                    "statements": [
                        {"text": "[FIXTURE] Evidence-based finding.", "citation_ids": refs}
                    ],
                }
            ),
            metadata(),
        )

    async def close(self):
        self.closed = True


class Knowledge:
    def __init__(self, chunks):
        self.chunks = chunks
        self.hits = chunks[:]
        self.queries = []
        self.missing = False

    async def inventory(self, sources, context):
        return len(self.chunks)

    async def search(self, query, sources, context, **kwargs):
        self.queries.append(query)
        return [SearchHit(chunk=c, ranking_score=0.7) for c in self.hits[: kwargs["top_k"]]]

    async def read(self, sources, context, *, limit, cursor):
        offset = int(cursor or 0)
        items = self.chunks[offset : offset + limit]
        return ChunkPage(
            items=items,
            total=len(self.chunks),
            next_cursor=str(offset + limit) if offset + limit < len(self.chunks) else None,
            inventory=CoverageInventory(
                expected_videos=len(sources),
                available_videos=len({c.video_id for c in self.chunks}),
                expected_chunks=None if self.missing else len(self.chunks),
                available_chunks=len(self.chunks),
                missing_sources=[source(VIDEO_B)] if self.missing else [],
                complete=not self.missing,
            ),
        )

    async def evidence(self, sources, ids, context):
        return [Evidence.model_validate(c.evidence()) for c in self.chunks if c.chunk_id in ids]


@pytest.fixture
def env():
    config = AnswerSettings(_env_file=None)
    model = ScriptedModel()
    knowledge = Knowledge([chunk()])
    return SimpleNamespace(
        config=config,
        model=model,
        knowledge=knowledge,
        ctx=Context(),
        sources=[source()],
        service=AnswerService(config, model, knowledge),
        request={"question": "RAG คืออะไร", "scope": {"video_ids": [VIDEO_A]}},
    )
