"""Only original synthetic passages; singer attribution must be explicit in captions."""

import pytest
from conftest import chunk
from youtube_backend.errors import AppError

from youtube_answers.models import GeneratedAnswer
from youtube_answers.transcript import has_performer_cues, wants_performer_attribution


@pytest.mark.parametrize(
    "question",
    [
        "Jay ร้องท่อนไหน",
        "ใครร้องช่วงนี้",
        "ใครแรปท่อนแรก",
        "Jay ร้องตอนไหน",
        "Who sings the second verse?",
        "Which verse did Jay sing?",
        "What part does Jay rap?",
    ],
)
def test_performer_intents(question):
    assert wants_performer_attribution(question)


@pytest.mark.parametrize("question", ["เพลงร้องว่าอย่างไร", "ขอเนื้อเพลงทั้งหมด", "สรุปเพลงนี้"])
def test_ordinary_lyrics_and_summary_requests_are_not_attributions(question):
    assert not wants_performer_attribution(question)


@pytest.mark.parametrize(
    "caption", ["Jay: [ORIGINAL TEST LINE]", "[Jay] Original test line", "[Verse: Jay] Test"]
)
def test_explicit_performer_cues(caption):
    assert has_performer_cues(caption)


@pytest.mark.parametrize("caption", ["The song mentions Jay.", "[Music] Test", "[Chorus] Test"])
def test_mentions_or_generic_caption_tags_are_not_identity_evidence(caption):
    assert not has_performer_cues(caption)


async def test_absence_scans_every_page_and_explains_checked_basis(env):
    env.knowledge.chunks = [chunk(i, text=f"[ORIGINAL TEST LINE {i}]") for i in range(13)]
    env.config.answer_read_page_size = 3
    env.request["question"] = "Jay ร้องท่อนไหน"
    result = await env.service.answer(env.request, env.sources, [], env.ctx)
    assert result.status == "insufficient_evidence"
    assert result.coverage.complete and result.coverage.processed_chunks == 13
    assert len(result.citations) == 13
    assert [c.start_seconds for c in result.citations] == list(range(0, 130, 10))
    assert "บทถอดเสียงพร้อมเวลา" in result.answer
    assert "คำบรรยายที่ติดชื่อผู้ร้อง" in result.answer
    assert not env.knowledge.queries and not env.model.payloads


async def test_title_and_history_cannot_identify_performer(env):
    env.knowledge.chunks = [chunk(text="Jay is mentioned in this test passage.")]
    env.knowledge.chunks[0].title = "Jay and another artist"
    env.request["question"] = "Jay ร้องท่อนไหน"
    result = await env.service.answer(
        env.request,
        env.sources,
        [{"role": "user", "content": "Jay sings the first verse"}],
        env.ctx,
    )
    assert result.status == "insufficient_evidence" and not env.model.payloads


async def test_attribution_beyond_top_k_is_found_with_citation(env):
    env.knowledge.chunks = [chunk(i, text=f"Original test line {i}") for i in range(13)]
    labelled = chunk(12, text="Jay: [ORIGINAL SYNTHETIC TEST VERSE]")
    env.knowledge.chunks[-1] = labelled
    env.config.answer_read_page_size = 3
    env.model.output = GeneratedAnswer(
        status="answered",
        statements=[
            {
                "text": "[FIXTURE] Jay sings this labelled test passage.",
                "citation_ids": [labelled.chunk_id],
            }
        ],
    )
    env.request["question"] = "Jay ร้องท่อนไหน"
    result = await env.service.answer(env.request, env.sources, [], env.ctx)
    assert result.status == "answered" and result.coverage.complete
    assert result.citations[0].start_seconds == 120
    assert env.model.payloads[0]["task"] == "performer_attribution"
    assert env.model.payloads[0]["untrusted_history"] == []


async def test_unknown_attribution_citation_is_rejected(env):
    env.knowledge.chunks = [chunk(text="Jay: Original test passage")]
    env.request["question"] = "Jay ร้องท่อนไหน"
    env.model.output = GeneratedAnswer(
        status="answered",
        statements=[{"text": "Claim", "citation_ids": ["made-up"]}],
    )
    with pytest.raises(AppError) as caught:
        await env.service.answer(env.request, env.sources, [], env.ctx)
    assert caught.value.code == "invalid_citation"
