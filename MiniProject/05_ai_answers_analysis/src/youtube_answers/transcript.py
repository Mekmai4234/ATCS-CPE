"""Transcript/performer intents and possible explicit caption attribution cues."""

import re


def wants_performer_attribution(question):
    text = question.casefold()
    return bool(
        re.search(r"(?:ร้อง|แรป).*(?:ท่อนไหน|ช่วงไหน|ตอนไหน)|ใคร.*(?:ร้อง|แรป)", text)
        or re.search(r"\bwho\b.*\b(?:sings?|sang|raps?|rapped)\b", text)
        or re.search(r"\b(?:which|what)\b.*\b(?:verse|part|section)\b.*\b(?:sing|sang|rap)", text)
        or re.search(r"\b(?:sings?|sang|raps?|rapped)\b.*\b(?:which|what)\b", text)
    )


def has_performer_cues(text):
    """Recognize possible explicit attributions, never infer identities from voices."""
    return bool(
        re.search(r"(?:^|\n)\s*[^\n:：\[\]]{1,80}[:：]\s*\S", text)
        or re.search(r"(?:^|\n)\s*\[[^\]\n]{1,80}[:：][^\]\n]+\]", text)
        or re.search(r"ร้องโดย|แรปโดย|ผู้ร้อง|vocals? by|performed by", text, re.I)
        or any(
            name.casefold()
            not in {
                "music",
                "instrumental",
                "applause",
                "laughter",
                "fixture",
                "chorus",
                "verse",
                "intro",
                "outro",
                "ดนตรี",
                "เสียงดนตรี",
            }
            for name in re.findall(r"(?:^|\n)\s*\[([^\]\n]{1,80})\]\s*\S", text)
        )
    )


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
