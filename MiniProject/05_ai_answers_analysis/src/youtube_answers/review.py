"""Local, versioned review signals. No provider calls or claims of semantic truth."""

import re
import unicodedata
from dataclasses import asdict, dataclass

POLICY_VERSION = "chat-review-draft-v1"
POLICY_VERSION_V2 = "chat-review-draft-v2"


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


def _review_signals(*, question, answer, status, citation_count, policy_version, quoted_study):
    signals = []
    if status == "insufficient_evidence":
        signals.append(ReviewSignal(policy_version, "insufficient_evidence"))
    if status == "answered" and citation_count == 0:
        signals.append(ReviewSignal(policy_version, "missing_citations"))
    text = inspection_text(question).casefold()
    if quoted_study and re.search(r"meaning|translate|quoted|ความหมาย|แปลว่า|หมายความว่า|คำว่า", text):
        text = re.sub('["“][^"“”\\n]{1,500}["”]|\\x27[^\\x27\\n]{1,500}\\x27', " ", text)

    if re.search(r"ignore\s+(?:all\s+)?(?:previous|system)\s+instructions|ลืมคำสั่งระบบ", text):
        signals.append(ReviewSignal(policy_version, "possible_instruction_override"))
    # A rule signal is review metadata, not an authorization to suppress output,
    # assert out-of-scope content, accuse a user, or confirm a factual error.
    return tuple(signals)


def review_signals(*, question, answer, status, citation_count):
    """Exact legacy v1 rules accepted by the merged 02 receiver."""
    return _review_signals(
        question=question,
        answer=answer,
        status=status,
        citation_count=citation_count,
        policy_version=POLICY_VERSION,
        quoted_study=False,
    )


def review_signals_v2(*, question, answer, status, citation_count):
    """Explicit experimental v2; never send to the v1 publication receiver."""
    return _review_signals(
        question=question,
        answer=answer,
        status=status,
        citation_count=citation_count,
        policy_version=POLICY_VERSION_V2,
        quoted_study=True,
    )


def review_envelope(*, question, answer, status, citation_count):
    """Proposed 05-to-02 payload; bind job/message/owner from trusted context at sink.

    Not automatically written to 02 tables or public AnswerResult. The 02 publisher
    must acknowledge a separately versioned sink before deployment can mount this.
    """
    return {
        "schema_version": 1,
        "signal_policy_version": POLICY_VERSION_V2,
        "source": "system_rule",
        "signals": [
            asdict(signal)
            for signal in review_signals_v2(
                question=question, answer=answer, status=status, citation_count=citation_count
            )
        ],
    }
