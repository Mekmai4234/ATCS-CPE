import time
from types import SimpleNamespace

import pytest
from youtube_backend.errors import LeaseLost
from youtube_backend.schemas import Evidence, ProviderMetadata, Source

from youtube_agent.config import AgentSettings
from youtube_agent.models import Generated, ModelReply
from youtube_agent.service import AgentService

VIDEO_A = "dQw4w9WgXcQ"
VIDEO_B = "jNQXAC9IVRw"


def metadata():
    return ProviderMetadata(
        provider="fixture",
        requested_model="fixture-scripted",
        usage={"input_tokens": 5},
        latency_ms=0,
    )


def evidence(
    video=VIDEO_A, cid="chunk-1", text="[FIXTURE] RAG retrieves evidence before answering."
):
    return Evidence(
        chunk_id=cid,
        video_id=video,
        transcript_version="v1",
        title="[FIXTURE] RAG",
        text=text,
        start_seconds=2,
        end_seconds=12,
    )


class Context:
    def __init__(self):
        self.end = time.monotonic() + 120
        self.events = []
        self.cancelled = False

    @property
    def remaining_seconds(self):
        return max(0, self.end - time.monotonic())

    def check(self):
        if self.cancelled:
            raise LeaseLost()

    def event(self, event):
        self.check()
        self.events.append(event)


class Knowledge:
    def __init__(self, records=None):
        self.records = [evidence(), evidence(cid="chunk-2")] if records is None else records
        self.calls = []
        self.search_limit = 1

    async def inventory(self, sources, context):
        context.check()
        return len(self.records)

    def selected(self, sources):
        return [e for e in self.records if e.video_id in {s.video_id for s in sources}]

    @staticmethod
    def chunk(e):
        return SimpleNamespace(evidence=lambda: e)

    async def search(self, query, sources, context, **kwargs):
        self.calls.append(("search", [s.video_id for s in sources], query))
        return [
            SimpleNamespace(chunk=self.chunk(e))
            for e in self.selected(sources)[: self.search_limit]
        ]

    async def read(self, sources, context, *, limit, cursor=None):
        self.calls.append(("read", [s.video_id for s in sources], cursor))
        records = self.selected(sources)
        offset = int(cursor or 0)
        page = records[offset : offset + limit]
        return SimpleNamespace(
            items=[self.chunk(e) for e in page],
            total=len(records),
            next_cursor=str(offset + limit) if offset + limit < len(records) else None,
        )

    async def evidence(self, sources, ids, context):
        return [e for e in self.selected(sources) if e.chunk_id in ids]


class ScriptedModel:
    def __init__(self, actions=None):
        self.actions = list(actions or [])
        self.history = []
        self.generated = []
        self.closed = False

    async def decide(self, history, timeout):
        self.history.append(list(history))
        action = self.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return ModelReply(*action, metadata())

    async def generate(self, request, records, schema, timeout):
        self.generated.append((request, records))
        cid = records[0].chunk_id
        content = {
            "study_plan": {
                "days": [
                    {"day": i, "topic": "[FIXTURE] Study RAG evidence", "citations": [cid]}
                    for i in range(1, request["days"] + 1)
                ]
            },
            "quiz": {
                "questions": [
                    {
                        "question": "[FIXTURE] What does RAG retrieve?",
                        "answer": "Evidence",
                        "explanation": records[0].text,
                        "citations": [cid],
                    }
                ]
            },
            "flashcards": {
                "cards": [
                    {"front": "[FIXTURE] RAG retrieval", "back": "Evidence", "citations": [cid]}
                ]
            },
        }[request["type"]]
        return Generated(schema.model_validate(content), metadata())

    async def close(self):
        self.closed = True


class BranchModel(ScriptedModel):
    """Deterministic observation-based test double, never advertised as real Gemini."""

    async def decide(self, history, timeout):
        self.history.append(list(history))
        observations = [h for h in history if h["role"] == "tool"]
        if not observations:
            return ModelReply("search_evidence", {"query": "RAG"}, metadata())
        records = observations[-1]["result"].get("evidence", [])
        if len(records) < 2:
            return ModelReply("read_video_chunks", {}, metadata())
        return ModelReply(
            "finish_research",
            {
                "content": "[FIXTURE] RAG retrieves evidence before answering.",
                "citation_ids": [r["chunk_id"] for r in records],
            },
            metadata(),
        )


@pytest.fixture
def unit():
    config = AgentSettings(_env_file=None)
    context = Context()
    knowledge = Knowledge()
    model = ScriptedModel()
    service = AgentService(config, model, knowledge)
    return SimpleNamespace(
        config=config,
        ctx=context,
        knowledge=knowledge,
        model=model,
        service=service,
        sources=[Source(video_id=VIDEO_A, generation=1, transcript_version="v1")],
        request={
            "goal": "Learn RAG",
            "scope": {"video_ids": [VIDEO_A]},
            "level": "beginner",
            "days": 7,
        },
    )
