"""Explicit transcript requests use stored captions, never generated replacement text."""

import re


def wants_transcript(question):
    text = re.sub(r"\s+", " ", question.casefold()).strip()
    text = text.replace("ไม่ต้องสรุป", "").replace("ไม่เอาสรุป", "")
    # Questions about meaning, a specific verse, translation, etc. remain RAG tasks.
    if any(
        word in text
        for word in (
            "สรุป",
            "ความหมาย",
            "วิเคราะห์",
            "แปล",
            "ไม่เอาเนื้อเพลง",
            "ไม่ต้องแสดง",
            "อย่าแสดง",
            "without lyrics",
            "don't show",
            "summar",
            "meaning",
            "analy",
            "translate",
            "which line",
            "chorus",
        )
    ):
        return False
    if "ท่อน" in text and not any(word in text for word in ("ทั้งหมด", "ครบ", "เต็ม")):
        return False
    return bool(
        re.search(r"เนื้อเพลง|บทถอดเสียง.*(?:ทั้งหมด|เต็ม)|(?:full|entire|all).*transcript", text)
        or re.search(r"(?:เพลง|เพลงนี้)(?:ร้องว่า|ร้อง|นี้ร้องว่า)(?:อย่างไร|ยังไง|อะไร)", text)
        or re.search(r"(?:full|entire|all|show|give|display).*\blyrics\b", text)
    )
