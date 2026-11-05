import socket

import pytest
from youtube_backend.document_store import publish

from youtube_rag.document_lookup import lookup, related_terms


@pytest.mark.asyncio
async def test_inverted_lookup_requires_full_phrase_and_keeps_unknown_end(env, monkeypatch):
    source = await env.ready()
    publish(
        env.db,
        dict(
            document_id="test",
            video_id=source.video_id,
            language="th",
            sha256="a" * 64,
            relative_path="source.txt",
            metadata={},
            timing_status="user_supplied_unverified",
            segments=[
                dict(
                    segment_id="1",
                    line=1,
                    text="ไทยค้นข้อความ good night",
                    start_seconds=10,
                    end_seconds=20,
                ),
                dict(
                    segment_id="2",
                    line=2,
                    text="good night อีกครั้ง",
                    start_seconds=30,
                    end_seconds=None,
                ),
            ],
        ),
    )
    queried = env.query(source.video_id)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("Network lookup"))
    result = lookup(queried.ctx, [source], ["GOOD NIGHT"])
    assert len(result["items"]) == 2 and result["items"][-1]["end_seconds"] is None
    assert result["provider_calls"] == 0
    assert not lookup(queried.ctx, [source], ["ค้นข้อที่ไม่มี"])["items"]
    assert not lookup(queried.ctx, [source], [], window=(30, 40))["items"]
    assert lookup(queried.ctx, [source], [], window=(15, 21))["items"][0]["start_seconds"] == 10


def test_related_terms_drop_question_words_but_keep_inner_syllables():
    terms = related_terms("Vector Database ใช้ทำอะไรครับ")
    assert terms[0] == ("exact", frozenset({"vector", "เวกเตอร์"}))
    assert terms[1] == ("exact", frozenset({"database", "ดาต้าเบส"}))
    assert terms[2][0] == "grams" and "ใช้" in terms[2][1]
    # "คะ" and "ไหม" are particles only at a word end.
    assert ("grams", frozenset({"คะแ", "ะแน", "แนน"})) in related_terms("คะแนนเท่าไหร่คะ")
    assert related_terms("อะไรครับ") == []
