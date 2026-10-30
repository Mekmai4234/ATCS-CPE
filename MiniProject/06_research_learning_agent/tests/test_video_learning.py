from types import SimpleNamespace

import pytest
from conftest import metadata
from youtube_backend.errors import AppError
from youtube_backend.schemas import AnswerResult, Citation, Coverage, QuizContent

from youtube_agent.models import Generated
from youtube_agent.video_learning import stored_video, video_artifact


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("stored", [False, True])
async def test_video_learning_preserves_real_observation_ids_and_partial_coverage(
    unit, unknown, stored, monkeypatch
):
    full_text = "Visible card. " * 20 + "This is a replay, not another opening."

    class Store:
        def __init__(self, context):
            pass

        def resolve(self, citations):
            return [
                dict(
                    evidence_id=c.chunk_id,
                    id="display-only-id",
                    kind="visual",
                    text=full_text,
                    video_id=c.video_id,
                    start_seconds=c.start_seconds,
                    end_seconds=c.end_seconds,
                )
                for c in citations
            ]

    monkeypatch.setattr("youtube_agent.video_learning.VideoEvidenceStore", Store)

    async def native(*args):
        return AnswerResult(
            status="answered",
            answer="A card is visible",
            citations=[
                Citation(
                    citation_id="1",
                    chunk_id="real-observation",
                    video_id=unit.sources[0].video_id,
                    title="A card is visible",
                    start_seconds=1,
                    end_seconds=2,
                    kind="video",
                    observation_cache_id="a" * 64,
                )
            ],
            coverage=Coverage(
                expected_videos=1, processed_videos=1, complete=False, notes=["Sampled frames only"]
            ),
            provider_metadata=metadata(),
        )

    async def generate(request, evidence, schema, timeout, **kwargs):
        assert kwargs["citation_key"] == "evidence_id"
        assert evidence[0].model_dump()["kind"] == "video_observation"
        assert evidence[0].model_dump()["text"] == full_text
        assert "replay" in evidence[0].model_dump()["text"]
        assert evidence[0].model_dump()["observation_kind"] == "visual"
        assert "id" not in evidence[0].model_dump()
        return Generated(
            schema.model_validate(
                {
                    "questions": [
                        {
                            "question": "What is visible?",
                            "answer": "A card",
                            "explanation": "Visible in sample",
                            "citations": ["fabricated" if unknown else "real-observation"],
                        }
                    ]
                }
            ),
            metadata(),
        )

    unit.service.media_answerer = native
    if stored:

        async def search(topic, sources, context, **kwargs):
            assert kwargs["kinds"] == ["video"]
            answer = await native()
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        ranking_score=1.0,
                        citation=answer.citations[0].model_dump(),
                        source=sources[0],
                    )
                ],
                notes=["Sampled video observations"],
            )

        unit.service.knowledge.rag = SimpleNamespace(
            evidence_library=lambda: SimpleNamespace(search=search),
        )

        async def forbidden(*args):
            raise AssertionError("Stored observations must avoid another video inference")

        unit.service.media_answerer = forbidden
    unit.service.model = SimpleNamespace(generate=generate)
    run = unit.service._run(unit.sources, unit.ctx)
    request = dict(type="quiz", topic="What is on screen?")
    if unknown:
        with pytest.raises(AppError, match="unknown observations"):
            await video_artifact(unit.service, request, run, QuizContent)
    else:
        result = await video_artifact(unit.service, request, run, QuizContent)
        assert result.citations[0].kind == "video"
        assert result.citations[0].citation_id == "real-observation"
        assert not result.coverage.complete


@pytest.mark.parametrize("kind,field", [("quiz", "question"), ("flashcards", "front")])
def test_rejects_duplicate_questions_or_cards_after_normalization(kind, field):
    from youtube_agent.quality import validate_learning_items

    with pytest.raises(AppError, match="repeats"):
        validate_learning_items(
            kind,
            [
                SimpleNamespace(**{field: "What is RAG?"}),
                SimpleNamespace(**{field: "what IS rag !"}),
            ],
        )
    validate_learning_items(
        kind,
        [
            SimpleNamespace(**{field: "What is RAG?"}),
            SimpleNamespace(**{field: "How do embeddings work?"}),
        ],
    )
    # Thai tone marks distinguish words; normalization must not erase them.
    validate_learning_items(
        kind, [SimpleNamespace(**{field: "ถามป้า"}), SimpleNamespace(**{field: "ถามปา"})]
    )


async def test_stored_video_does_not_enable_multiclip_native_learning(unit):
    sources = [unit.sources[0], unit.sources[0].model_copy(update={"video_id": "jNQXAC9IVRw"})]
    run = unit.service._run(sources, unit.ctx)
    assert await stored_video(unit.service, {"topic": "visual scene"}, run) is None
