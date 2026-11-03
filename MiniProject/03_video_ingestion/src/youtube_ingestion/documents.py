"""Strict, offline reader for the explicitly mapped user-supplied documents."""

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Passage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    line: int
    text: str
    start_seconds: float
    end_seconds: float | None
    end_method: str


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    relative_path: str
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    language: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    import_version: str
    source_type: str = "user_supplied"
    timing_status: str = "user_supplied_unverified"
    metadata: dict[str, str] = Field(default_factory=dict)
    headings: dict[str, str] = Field(default_factory=dict)
    segments: list[Passage] = Field(default_factory=list)


HEADERS = {"SINGLE": "single", "ARTIST": "artist", "เจ้าของคลิป": "channel", "ร้านในคลิป": "shop"}
TIMED = re.compile(r"^\[(\d{2,}:\d{2})\] - \[(\d{2,}:\d{2}|ไม่ระบุ)\] (.+)$")


def seconds(value):
    minute, second = map(int, value.split(":"))
    if second >= 60:
        raise ValueError("Seconds must be below 60")
    return minute * 60 + second


def parse(root: Path, specification: dict) -> Document:
    document = Document.model_validate(specification)
    if (
        document.source_type != "user_supplied"
        or document.timing_status != "user_supplied_unverified"
    ):
        raise ValueError("Unsupported provenance")
    relative = Path(document.relative_path)
    root = root.resolve(strict=True)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".txt":
        raise ValueError("Document path must be a relative .txt within Transcript")
    path = root / relative
    if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
        raise ValueError("Symlink document paths are forbidden")
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("Document escapes Transcript")
    if path.stat().st_size > 4_000_000:
        raise ValueError("Document exceeds byte limit")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != document.sha256:
        raise ValueError("Source hash mismatch: " + document.document_id)
    metadata, passages = {}, []
    for line, text in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not text.strip():
            continue
        if str(line) in document.headings and document.headings[str(line)] == text:
            continue
        match = TIMED.fullmatch(text)
        if not match:
            key, separator, value = text.partition(":")
            if passages or not separator or key.strip() not in HEADERS or not value.strip():
                raise ValueError(f"{document.document_id}:{line}: invalid passage or header")
            field = HEADERS[key.strip()]
            if field in metadata:
                raise ValueError(f"{document.document_id}:{line}: duplicate metadata")
            metadata[field] = value.strip()
            continue
        start = seconds(match[1])
        end = None if match[2] == "ไม่ระบุ" else seconds(match[2])
        if end is not None and end <= start:
            raise ValueError(f"{document.document_id}:{line}: nonpositive interval")
        if passages and (passages[-1].end_seconds is None or start < passages[-1].end_seconds):
            raise ValueError(f"{document.document_id}:{line}: overlap or unknown nonfinal end")
        passages.append(
            Passage(
                segment_id=f"{document.document_id}:{line}",
                line=line,
                text=match[3].strip(),
                start_seconds=start,
                end_seconds=end,
                end_method="unknown" if end is None else "document_boundary",
            )
        )
    if not passages or len(passages) > 100_000:
        raise ValueError("Document needs bounded nonempty passages")
    for previous, following in zip(passages, passages[1:], strict=False):
        if previous.end_seconds == following.start_seconds:
            previous.end_method = "next_segment_start"
    return document.model_copy(update={"metadata": metadata, "segments": passages})


def load(root: Path) -> list[Document]:
    manifest = root / "manifest.json"
    if manifest.is_symlink() or manifest.stat().st_size > 100_000:
        raise ValueError("Invalid manifest")
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError("Expected a bounded document allowlist")
    documents = [parse(root, entry) for entry in entries]
    for field in ("document_id", "video_id", "relative_path"):
        values = [getattr(d, field) for d in documents]
        if len(values) != len(set(values)):
            raise ValueError("Duplicate manifest " + field)
    return documents
