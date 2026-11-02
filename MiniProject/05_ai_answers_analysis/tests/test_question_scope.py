import pytest

from youtube_answers.question_scope import is_followup, retrieval_query


@pytest.mark.parametrize(
    "question",
    [
        "ช่วยยกตัวอย่างให้เข้าใจง่าย",
        "ขยายความหน่อยครับ",
        "ช่วย ยกตัวอย่างให้เข้าใจง่ายหน่อยนะคะ?!",
        "ขอช่วยอธิบายเพิ่มเติมหน่อยนะครับ",
    ],
)
def test_natural_followups_require_a_user_topic_and_skip_followup_chains(question):
    assert is_followup(question)
    assert retrieval_query(question, []) == ""
    assert retrieval_query(question, [{"role": "assistant", "content": "RAG"}]) == ""
    history = [
        {"role": "user", "content": "RAG คืออะไร"},
        {"role": "assistant", "content": "RAG retrieves evidence"},
        {"role": "user", "content": "ขยายความหน่อยครับ"},
    ]
    assert retrieval_query(question, history) == "RAG คืออะไร"


@pytest.mark.parametrize(
    "question",
    [
        "ช่วยอธิบาย photosynthesis หน่อยครับ",
        "ช่วยยกตัวอย่าง photosynthesis ให้เข้าใจง่าย",
        "ขยายความเรื่องการสังเคราะห์ด้วยแสงหน่อยค่ะ",
        "ขยายความหน่อยครับ แล้ว photosynthesis คืออะไร",
    ],
)
def test_polite_independent_questions_never_inherit_previous_topic(question):
    assert not is_followup(question)
    assert retrieval_query(question, [{"role": "user", "content": "RAG คืออะไร"}]) == question
