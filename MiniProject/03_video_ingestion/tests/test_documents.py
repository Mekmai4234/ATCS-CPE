import hashlib
import socket
from pathlib import Path

import pytest

from youtube_ingestion.documents import load, parse


def spec(root, text):
    raw = text.encode("utf-8-sig")
    (root / "source.txt").write_bytes(raw)
    return dict(
        document_id="test-document",
        relative_path="source.txt",
        video_id="C0DXctGPWxw",
        language="th",
        sha256=hashlib.sha256(raw).hexdigest(),
        import_version="v1",
    )


def test_real_sources_offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Document validation attempted network")

    monkeypatch.setattr(socket, "create_connection", denied)
    documents = load(Path(__file__).resolve().parents[2] / "Transcript")
    assert len(documents) == 5
    assert sum(len(d.segments) for d in documents) == 934
    assert all(d.segments[-1].end_seconds is None for d in documents)
    dice = next(d for d in documents if d.video_id == "C0DXctGPWxw")
    assert dice.metadata == {"single": "รอ SIS (TER)", "artist": "DICEBLUE"}
    assert any("good night" in s.text.casefold() for s in dice.segments)


def test_bom_crlf_metadata_and_unknown_end(tmp_path):
    document = parse(
        tmp_path, spec(tmp_path, "ARTIST : Test\r\n[00:01] - [00:03] A\r\n[00:03] - [ไม่ระบุ] B\r\n")
    )
    assert document.segments[0].end_method == "next_segment_start"
    assert document.segments[1].end_seconds is None
    assert document.metadata["artist"] == "Test"


@pytest.mark.parametrize(
    "text",
    [
        "[00:60] - [01:02] invalid",
        "[00:01] - [00:03]   ",
        "[00:03] - [00:01] reversed",
        "[00:01] - [00:04] A\n[00:03] - [00:05] overlap",
        "[00:01] - [ไม่ระบุ] A\n[00:03] - [00:05] nonfinal",
        "[00:01] - [00:04] A\nbroken passage",
        "ARTIST : A\nARTIST : B",
    ],
)
def test_malformed_document_rejected(tmp_path, text):
    with pytest.raises(ValueError):
        parse(tmp_path, spec(tmp_path, text))


def test_hash_and_path_escape_rejected(tmp_path):
    entry = spec(tmp_path, "[00:01] - [ไม่ระบุ] A")
    with pytest.raises(ValueError, match="hash"):
        parse(tmp_path, {**entry, "sha256": "a" * 64})
    with pytest.raises(ValueError, match="relative"):
        parse(tmp_path, {**entry, "relative_path": "../source.txt"})
