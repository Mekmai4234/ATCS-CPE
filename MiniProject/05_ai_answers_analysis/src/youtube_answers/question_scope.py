"""Conservative retrieval context and the shared bounded video-clock contract."""

import re

from .models import error

RETRIEVAL_VERSION = "latest-topic-clock-v1"

CLOCK = re.compile(r"(?<![\d:])[\d:]*\d:[\d:]+(?![\d:])")
FOLLOWUP = re.compile(
    r"(?:explain(?: more| further)?|tell me more|expand(?: on that)?"
    r"|give (?:me )?(?:an? )?examples?"
    r"|continue|more details?(?: please)?|how does (?:that|it) work"
    r"|ขยายความ(?:หน่อย|เพิ่มเติม)?|อธิบาย(?:เพิ่ม(?:เติม)?|อีกครั้ง)(?:หน่อย)?"
    r"|ยกตัวอย่าง(?:เรื่อง(?:นั้น|เดิม))?(?:หน่อย)?|ขอรายละเอียด(?:เพิ่ม(?:เติม)?)?"
    r"|ต่อจากเดิม|เรื่องนั้นคืออะไร|ทำงานอย่างไร)",
    re.I,
)


def is_followup(question):
    return bool(FOLLOWUP.fullmatch(re.sub(r"[?!.ๆ\s]+$", "", question.strip())))


def retrieval_query(question, history):
    """Independent questions never inherit unrelated words; ambiguous context abstains."""
    if not is_followup(question):
        return question
    # Do not collect an entire conversation or combine separate topics.
    for item in reversed(history[-12:]):
        content = item.get("content")
        if item.get("role") == "user" and isinstance(content, str) and not is_followup(content):
            if len(content.encode()) <= 5000:
                return content
            break
    return ""


def time_window(question, source):
    if not CLOCK.search(question):
        return None
    try:
        from youtube_ingestion.video_plan import VideoPlan
    except ImportError:
        raise error(
            "integration_not_installed", "Install the shared video time parser", status=503
        ) from None
    plan = VideoPlan.from_question(source, question)
    return plan.start_seconds, plan.end_seconds


def overlaps(record, window):
    return window is None or (record.end_seconds > window[0] and record.start_seconds < window[1])


def lexical_query(question):
    # Remove framing words/times that otherwise match unrelated transcript material.
    question = CLOCK.sub(" ", question)
    question = re.sub(
        r"\b(?:what|is|are|the|a|an|about|explain|please|in|clip|video|at|to|until|through)\b",
        " ",
        question,
        flags=re.I,
    )
    question = re.sub(
        r"ช่วงเวลา|ในคลิป|จากคลิป|กล่าวถึงอะไร|คืออะไร|อธิบาย|เกี่ยวกับ|นาที|จนถึง|ถึง", " ", question
    )
    return " ".join(question.split()).strip(" -–—?!.,")


def relevant(query, text):
    """Lexical evidence, never semantic confidence: no Thai bigram-only positives."""
    latin = set(re.findall(r"[a-z][a-z0-9]*", query.casefold()))
    words = set(re.findall(r"[a-z][a-z0-9]*", text.casefold()))
    thai = re.findall(r"[\u0e00-\u0e7f]{3,}", query)
    return bool(latin & words or any(term in text for term in thai))


def requires_visual(question):
    return bool(
        re.search(r"ในภาพ|บนจอ|เห็นอะไร|สีอะไร|แต่งตัว|on.screen|what.*wear|what.*see", question, re.I)
    )
