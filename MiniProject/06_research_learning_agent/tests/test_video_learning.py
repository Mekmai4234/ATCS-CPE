from types import SimpleNamespace

import pytest
from conftest import metadata
from youtube_backend.errors import AppError
from youtube_backend.schemas import AnswerResult, Citation, Coverage, QuizContent

from youtube_agent.models import Generated
from youtube_agent.video_learning import video_artifact


@pytest.mark.parametrize("unknown", [False, True])
async def test_video_learning_preserves_real_observation_ids_and_partial_coverage(unit, unknown):
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
