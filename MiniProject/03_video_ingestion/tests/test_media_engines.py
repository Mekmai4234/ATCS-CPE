"""Opt-in REAL local FFmpeg/Tesseract acceptance, with a self-created silent clip.

Set MEDIA_TEST_TOOLS to a directory containing ffmpeg(.exe), ffprobe(.exe),
tesseract/tesseract(.exe), and tessdata/{tha,eng}.traineddata. No cloud calls.
"""

import os
from pathlib import Path

import pytest
from conftest import Context
from PIL import Image, ImageDraw, ImageFont
from youtube_backend.errors import AppError

from youtube_ingestion.config import MediaSettings
from youtube_ingestion.local_tools import LocalTools
from youtube_ingestion.media import MediaPreparation


@pytest.fixture
async def engine_media(tmp_path):
    configured = os.environ.get("MEDIA_TEST_TOOLS")
    if not configured:
        pytest.skip("Set MEDIA_TEST_TOOLS for explicit local-engine acceptance")
    root = Path(configured).resolve()
    suffix = ".exe" if os.name == "nt" else ""
    settings = MediaSettings(
        _env_file=None,
        enabled=True,
        upload_root=tmp_path / "uploads",
        work_root=tmp_path / "private",
        sample_interval_seconds=1,
        ffmpeg=str(root / ("ffmpeg" + suffix)),
        ffprobe=str(root / ("ffprobe" + suffix)),
        tesseract=str(root / "tesseract" / ("tesseract" + suffix)),
        tessdata_dir=root / "tessdata",
    )
    settings.upload_root.mkdir()
    service = MediaPreparation(settings)
    try:
        yield settings, service
    finally:
        await service.close()


async def test_real_silent_clip_thai_english_ocr_and_resume(engine_media, tmp_path):
    settings, service = engine_media
    # Targets fall between source frames: stored timestamps must come from decoder PTS.
    settings.max_frames = 4
    settings.sample_interval_seconds = 0.7
    font_path = os.environ.get("MEDIA_TEST_FONT", "C:/Windows/Fonts/tahoma.ttf")
    if not Path(font_path).is_file():
        pytest.fail("MEDIA_TEST_FONT must be an installed Thai/English font")
    image = Image.new("RGB", (1280, 720), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 72)
    latin_font = ImageFont.truetype(os.environ.get("MEDIA_TEST_LATIN_FONT", font_path), 72)
    draw.text((80, 150), "RAG BUDDY", font=latin_font, fill="black")
    draw.text((80, 300), "ทดสอบภาษาไทย", font=font, fill="black")
    title = tmp_path / "title.png"
    image.save(title)
    clip = settings.upload_root / "silent.mkv"
    # FFV1 is lossless: identical recurring frames can safely reuse OCR by exact hash.
    # Fixture encoding needs a larger virtual-address budget on Linux FFV1.
    # The actual product's decoding/OCR below retains its original memory cap.
    encoder = LocalTools(settings.model_copy(update={"memory_mb": max(2048, settings.memory_mb)}))
    try:
        await encoder.run(
            [
                settings.ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-loop",
                "1",
                "-i",
                title,
                "-t",
                "3",
                "-r",
                "4",
                "-an",
                "-c:v",
                "ffv1",
                "-threads",
                "1",
                clip,
            ],
            Context(),
        )
    finally:
        await encoder.close()
    result = await service.prepare(clip, Context())
    assert not result.info.has_audio and not result.info.has_subtitle_stream
    assert [f.timestamp_seconds for f in result.frames] == [0.5, 1.25, 2.0, 2.75]
    assert result.frames[0].seek_timestamp_seconds == 0.375
    assert result.frames[0].timestamp_basis == "decoded_stream_pts"
    text = result.frames[0].ocr.text
    assert "RAG" in text and "BUDDY" in text
    assert any("\u0e00" <= c <= "\u0e7f" for c in text), text
    assert result.frames[0].ocr.engine_version.startswith("tesseract")
    assert result.frames[0].ocr.words[0].confidence >= 0
    assert len({f.sha256 for f in result.frames}) == 1
    replay = await service.prepare(clip, Context())
    assert replay == result
    (tmp_path / "local-media-report.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )


async def test_real_corrupt_media_is_bounded_and_leaves_no_scratch(engine_media):
    settings, service = engine_media
    clip = settings.upload_root / "corrupt.mp4"
    clip.write_bytes(b"not a video")
    with pytest.raises(AppError) as error:
        await service.prepare(clip, Context())
    assert error.value.code == "media_tool_failed"
    assert not list(settings.work_root.glob("preparing-*"))
