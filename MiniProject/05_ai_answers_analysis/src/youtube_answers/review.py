"""Local, versioned review signals. No provider calls or claims of semantic truth."""

import re
import unicodedata
from dataclasses import dataclass

POLICY_VERSION = "chat-review-draft-v1"


@dataclass(frozen=True)
class ReviewSignal:
    policy_version: str
    reason: str
    source: str = "system_rule"
    confirmed: bool = False


def inspection_text(text):
    # Preserve original text externally and retain Thai combining marks.
    normalized = unicodedata.normalize("NFC", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Cf")


def review_signals(*, question, answer, status, citation_count):
    signals = []
    if status == "insufficient_evidence":
        signals.append(ReviewSignal(POLICY_VERSION, "insufficient_evidence"))
    if status == "answered" and citation_count == 0:
        signals.append(ReviewSignal(POLICY_VERSION, "missing_citations"))
    text = inspection_text(question).casefold()
    if re.search(r"ignore\s+(?:all\s+)?(?:previous|system)\s+instructions|ลืมคำสั่งระบบ", text):
        signals.append(ReviewSignal(POLICY_VERSION, "possible_instruction_override"))
    # A rule signal is review metadata, not an authorization to suppress output,
    # assert out-of-scope content, accuse a user, or confirm a factual error.
    return tuple(signals)
