"""Deterministic document answers. This module has no model/provider client."""

import re
import time

from youtube_backend.document_store import read
from youtube_backend.schemas import AnswerResult, Citation, Coverage, ProviderMetadata
from youtube_rag.document_lookup import lookup, query_phrases

from .authorization import MemberContext, guard_context
from .question_scope import is_followup, requires_visual, retrieval_query, time_window

POLICY = "transcript-first-v1"


def metadata_intent(question):
    if re.search(
        r"คำว่า|ประโยค|ตรงไหน|ช่วง|\d:\d|สื่อความหมาย|วิเคราะห์|ยกตัวอย่าง|อธิบายใหม่|สีอะไร|สีเสื้อ", question
    ):
        return None
    question = re.sub(r"\s+", "", question).casefold()
    for field, aliases in {
        "single": ("ชื่อเพลง", "เพลงนี้ชื่อ", "เพลงอะไร", "songtitle"),
        "artist": ("ใครร้อง", "ศิลปิน", "นักร้อง", "whosings", "artist"),
        "channel": ("เจ้าของคลิป", "ช่องอะไร", "ชื่อช่อง", "ใครทำคลิป", "channel"),
        "shop": ("ร้านอะไร", "ชื่อร้าน", "ร้านในคลิป"),
    }.items():
        if any(alias in question for alias in aliases):
            return field
    return None


def document_answer(request, sources, history, context):
    started = time.perf_counter()
    context = guard_context(context, sources, {"chat"})
    if isinstance(context, MemberContext):
        context.conversation(request.get("conversation_id"))
        history = context.history(history)
    documents = read(context, sources)
    if not documents:
        return None
    question = request["question"]
    field = metadata_intent(question)
    citations, paragraphs, notes = [], [], ["ตอบจากไฟล์ในเครื่อง · ไม่ใช้ AI · provider calls 0"]
    if field:
        labels = dict(single="ชื่อเพลง", artist="ศิลปิน", channel="เจ้าของคลิปตามเอกสาร", shop="ร้านในคลิป")
        for document in documents:
            value = document["data"]["metadata"].get(field)
            if value:
                citation = Citation(
                    citation_id=str(len(citations) + 1),
                    chunk_id="metadata:" + field,
                    video_id=document["video_id"],
                    title=document["data"]["relative_path"],
                    kind="document_metadata",
                    document_id=document["document_id"],
                    document_version=document["version"],
                    source_hash=document["source_hash"],
                    metadata_field=field,
                )
                citations.append(citation)
                paragraphs.append(f"{labels[field]}: {value} [{citation.citation_id}]")
            else:
                paragraphs.append(f"เอกสารของคลิป {document['video_id']} ไม่ระบุ{labels[field]}")
    elif requires_visual(question) or re.search(r"สีเสื้อ|ใส่เสื้อ|แต่งกาย|ภาพใน|ใน\s*mv", question, re.I):
        paragraphs.append("บทถอดเสียงยืนยันภาพในคลิปไม่ได้ ต้องตรวจหลักฐานภาพก่อน จึงไม่เดาคำตอบจากไฟล์ข้อความ")
    elif re.search(r"ใครร้อง|ผู้ร้อง|ศิลปิน", question) and time_window(question, sources[0]):
        paragraphs.append("ข้อมูลศิลปินในเอกสารไม่ระบุว่าใครร้องแต่ละช่วง จึงยังยืนยันผู้ร้องตามเวลาที่ถามไม่ได้")
    elif is_followup(question) or re.search(
        r"ยกตัวอย่าง|สื่อความหมาย|วิเคราะห์|สรุป|กำไรสุทธิ|อธิบายใหม่", question
    ):
        topic = retrieval_query(question, history)
        paragraphs.append(
            "คำถามนี้ต้องใช้การอธิบายหรือวิเคราะห์เพิ่มเติม เลือก “ให้ AI ช่วยอธิบาย” "
            "เพื่อใช้ AI กับคลิปที่เลือก โดยอยู่ภายใต้โควตาปัจจุบัน"
        )
        if topic and topic != question:
            notes.append("หัวข้อจากคำถามก่อนหน้า: " + topic[:200])
    else:
        window = time_window(question, sources[0])
        result = lookup(context, sources, query_phrases(question), window=window)
        notes.append(
            f"ค้นด้วยข้อความตรง · ตรวจผู้สมัคร {result['candidates_examined']} ช่วง · ไม่ใช่การตรวจเสียง/ภาพ"
        )
        if not result["scan_complete"] or result["truncated"]:
            notes.append("แสดงผลบางส่วนตามขีดจำกัด ไม่ยืนยันว่าครอบคลุมทุกตำแหน่ง")
        for item in result["items"]:
            citation = Citation(
                citation_id=str(len(citations) + 1),
                chunk_id=item["segment_id"],
                video_id=item["video_id"],
                title=item["title"],
                kind="document_transcript",
                start_seconds=item["start_seconds"],
                end_seconds=item["end_seconds"],
                document_id=item["document_id"],
                document_version=item["document_version"],
                source_hash=item["source_hash"],
                document_line=item["line"],
            )
            citations.append(citation)
            paragraphs.append(f"{item['text']} [{citation.citation_id}]")
            if window and (item["start_seconds"] < window[0] or item["end_seconds"] > window[1]):
                notes.append("ข้อความบางส่วนคร่อมขอบช่วงที่ขอ แสดงเวลาเดิมตามเอกสาร")
        if not citations:
            paragraphs.append(
                "ยังไม่พบข้อความตรงคำค้นในขอบเขตที่ตรวจ ลองระบุคำพูดหรือช่วงเวลาให้ชัดขึ้น "
                "การค้นไม่พบไม่ยืนยันว่าไม่มีข้อมูลทั้งคลิป"
            )
        notes.append("เวลาจากเอกสารผู้ใช้ ยังไม่ได้เทียบเสียงจริง; เวลาจบที่ไม่ทราบยังคงไม่ระบุ")
    context.check()
    return AnswerResult(
        status="answered" if citations else "insufficient_evidence",
        answer="\n\n".join(paragraphs),
        citations=citations,
        coverage=Coverage(
            expected_videos=len(sources),
            processed_videos=0,
            expected_chunks=None,
            processed_chunks=None,
            complete=False,
            notes=notes,
        ),
        provider_metadata=ProviderMetadata(
            provider="local-document",
            requested_model="none",
            usage={},
            latency_ms=(time.perf_counter() - started) * 1000,
        ),
    )
