"""Original synthetic captions only; no copyrighted song text in test fixtures."""

import pytest
from conftest import chunk
from youtube_backend.errors import AppError
from youtube_backend.schemas import Segment

from youtube_answers.transcript import wants_transcript


@pytest.mark.parametrize(
    "question",
    [
        "ขอเนื้อเพลงทั้งหมด",
        "ขอเนื้อเพลงครบทุกท่อน ไม่ต้องสรุป",
        "เพลงร้องว่าอย่างไร",
        "เพลงนี้ร้องยังไง",
        "แสดงบทถอดเสียงทั้งหมด",
        "Show full lyrics",
        "Give me the entire transcript",
    ],
)
def test_explicit_transcript_intents(question):
    assert wants_transcript(question)


@pytest.mark.parametrize(
    "question",
    [
        "สรุปเนื้อเพลง",
        "เนื้อเพลงมีความหมายอย่างไร",
        "ขอเนื้อเพลงท่อนแรก",
        "แปลเนื้อเพลง",
        "Summarize the lyrics",
        "What is the chorus meaning?",
        "Explain RAG",
        "ไม่ต้องแสดงเนื้อเพลง",
        "อย่าแสดงเนื้อเพลง",
    ],
)
def test_other_questions_remain_rag(question):
    assert not wants_transcript(question)


def segment(i, text):
    return Segment(segment_id=f"s{i}", text=text, start_seconds=i * 10, duration_seconds=10)


async def test_transcript_reads_all_pages_not_top_k_and_never_generates(env):
    env.config.answer_read_page_size = 3
    originals = [segment(i, f"[ORIGINAL TEST CAPTION {i:02d}]") for i in range(13)]
    env.knowledge.chunks = [chunk(i, text=s.text) for i, s in enumerate(originals)]

    async def read_transcript(source, context):
        return originals

    env.knowledge.transcript = read_transcript
    env.request["question"] = "ขอเนื้อเพลงทั้งหมด"
    result = await env.service.answer(env.request, env.sources, [], env.ctx)
    assert result.coverage.complete
    assert result.coverage.processed_chunks == result.coverage.expected_chunks == 13
    assert len(result.citations) == 13
    assert all(result.answer.count(s.text) == 1 for s in originals)
    assert [result.answer.index(s.text) for s in originals] == sorted(
        result.answer.index(s.text) for s in originals
    )
    assert not env.model.payloads and not env.knowledge.queries
    assert result.provider_metadata.provider == "transcript"
    assert result.provider_metadata.requested_model == "none"


async def test_original_repetitions_preserved_without_rag_overlap_duplication(env):
    repeated = "[ORIGINAL TEST REFRAIN]"
    first, second = chunk(0, text=repeated), chunk(1, text=repeated + "\n" + repeated)
    second.segment_ids = ["s0", "s1"]
    env.knowledge.chunks = [first, second]

    async def read_transcript(source, context):
        return [segment(0, repeated), segment(1, repeated)]

    env.knowledge.transcript = read_transcript
    env.request["question"] = "เพลงร้องว่าอย่างไร"
    result = await env.service.answer(env.request, env.sources, [], env.ctx)
    assert result.answer.count(repeated) == 2
    assert result.coverage.complete and len(result.citations) == 2


async def test_transcript_index_disagreement_cannot_claim_complete(env):
    async def read_transcript(source, context):
        return [segment(1, "[CAPTION ABSENT FROM INDEX]")]

    env.knowledge.transcript = read_transcript
    env.request["question"] = "ขอเนื้อเพลงทั้งหมด"
    with pytest.raises(AppError) as caught:
        await env.service.answer(env.request, env.sources, [], env.ctx)
    assert caught.value.code == "source_changed"


async def test_oversized_transcript_fails_instead_of_silent_truncation(env):
    async def read_transcript(source, context):
        return [segment(0, "x" * 11001)]

    env.knowledge.transcript = read_transcript
    env.request["question"] = "ขอเนื้อเพลงทั้งหมด"
    with pytest.raises(AppError) as caught:
        await env.service.answer(env.request, env.sources, [], env.ctx)
    assert caught.value.code == "transcript_too_large"


async def test_access_revoked_during_transcript_read_blocks_result(env):
    async def read_transcript(source, context):
        env.ctx.failure = AppError("member_access_denied", "Access revoked", 403)
        return [segment(0, "[ORIGINAL TEST CAPTION]")]

    env.knowledge.transcript = read_transcript
    env.request["question"] = "ขอเนื้อเพลงทั้งหมด"
    with pytest.raises(AppError) as caught:
        await env.service.answer(env.request, env.sources, [], env.ctx)
    assert caught.value.code == "member_access_denied"
