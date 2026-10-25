import asyncio
import io
import json

import pytest
from conftest import Context
from PIL import Image
from youtube_backend.errors import AppError

from youtube_ingestion.config import MediaSettings
from youtube_ingestion.media import MediaPreparation


def png(colour="white"):
    image = Image.new("RGB", (64, 32), colour)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class Tools:
    def __init__(self):
        self.calls = []
        self.info = dict(
            format={"duration": "90", "start_time": "0"},
            streams=[
                dict(index=0, codec_type="video", width=64, height=32, avg_frame_rate="25/1"),
            ],
        )
        self.fail_at = None
        self.cancel_at = None
        self.images = [png()] * 12
        self.text = "PRODUCT"

    async def run(self, command, context, **kwargs):
        command = list(map(str, command))
        self.calls.append(command)
        if command[0] == "ffprobe":
            return json.dumps(self.info).encode()
        if command[1] in {"--version", "-version"}:
            return b"test-engine-v1\n"
        if command[0] == "tesseract":
            return (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                f"5\t1\t1\t1\t1\t1\t1\t1\t20\t10\t92.5\t{self.text}\n"
            ).encode()
        count = sum(c[0] == "ffmpeg" and "-ss" in c for c in self.calls)
        if count == self.cancel_at:
            raise asyncio.CancelledError
        if count == self.fail_at:
            raise AppError("media_timeout", "Fixture timeout", 504, True)
        timestamp = command[command.index("-ss") + 1]
        return self.images[
            count - 1
        ], f"[Parsed_showinfo_0] n: 0 pts: 0 pts_time:{timestamp} fmt:rgb24".encode()

    async def close(self):
        pass

    def count(self, tool):
        return sum(c[0] == tool and c[1] not in {"-version", "--version"} for c in self.calls)


@pytest.fixture
def media(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = uploads / "silent.mp4"
    source.write_bytes(b"[FIXTURE] local immutable authorized upload")
    models = tmp_path / "tessdata"
    models.mkdir()
    for lang in ("tha", "eng"):
        (models / f"{lang}.traineddata").write_bytes(lang.encode())
    settings = MediaSettings(
        _env_file=None,
        enabled=True,
        upload_root=uploads,
        work_root=tmp_path / "private",
        tessdata_dir=models,
        sample_interval_seconds=30,
    )
    tools = Tools()
    service = MediaPreparation(settings, tools=tools)
    return source, service, tools


async def test_silent_clip_local_ocr_keeps_every_occurrence_and_reuses_work(media):
    source, service, tools = media
    result = await service.prepare(source, Context())
    assert result.kind == "media" and not result.info.has_audio
    assert result.visual_analysis == "not_requested"
    assert [f.timestamp_seconds for f in result.frames] == [15, 45, 75]
    assert len({f.frame_id for f in result.frames}) == 3
    assert len({f.sha256 for f in result.frames}) == 1
    assert result.frames[1].near_duplicate_of == result.frames[0].frame_id
    assert tools.count("tesseract") == 1
    assert all(f.ocr.text == "PRODUCT" and f.ocr.kind == "ocr" for f in result.frames)
    assert not result.coverage.whole_video_reviewed
    assert len(result.coverage.unsampled_intervals) == 4
    assert result.stored_image_bytes == len(png())
    assert all((service.settings.work_root / f.asset_key).is_file() for f in result.frames)
    assert not list(service.settings.work_root.glob("preparing-*"))
    before = tools.count("ffmpeg"), tools.count("tesseract")
    replay = await service.prepare(source, Context())
    assert replay == result
    assert (tools.count("ffmpeg"), tools.count("tesseract")) == before


async def test_unreadable_ocr_preserves_image_for_visual_path(media):
    source, service, tools = media
    tools.text = ""
    result = await service.prepare(source, Context())
    assert result.frames[0].ocr.status == "empty"
    assert result.frames[0].selected_for_vision
    assert (service.settings.work_root / result.frames[0].asset_key).is_file()


async def test_missing_thai_model_is_explicit_and_never_cloud_fallback(media):
    source, service, tools = media
    (service.settings.tessdata_dir / "tha.traineddata").unlink()
    result = await service.prepare(source, Context())
    assert result.frames[0].ocr.reason == "ocr_language_unavailable"
    assert result.frames[0].ocr.status == "unavailable"
    assert tools.count("tesseract") == 0
    assert result.frames[0].asset_key.endswith(".png")


@pytest.mark.parametrize("cancel", [False, True])
async def test_checkpoint_survives_timeout_or_cancellation_then_resumes(media, cancel):
    source, service, tools = media
    if cancel:
        tools.cancel_at = 2
    else:
        tools.fail_at = 2
    with pytest.raises(asyncio.CancelledError if cancel else AppError):
        await service.prepare(source, Context())
    checkpoint = next(service.settings.work_root.glob("*/checkpoint.json"))
    assert len(json.loads(checkpoint.read_text())["frames"]) == 1
    assert not list(service.settings.work_root.glob("preparing-*"))
    assert not list(service.settings.work_root.glob("*/*.partial"))
    tools.fail_at = tools.cancel_at = None
    result = await service.prepare(source, Context())
    assert len(result.frames) == 3
    assert tools.count("ffmpeg") == 4  # One complete, one interrupted, two resumed.
    assert tools.count("tesseract") == 1


async def test_model_change_redoes_ocr_without_extracting_frames(media):
    source, service, tools = media
    first = await service.prepare(source, Context())
    (service.settings.tessdata_dir / "tha.traineddata").write_bytes(b"new-version")
    second = await service.prepare(source, Context())
    assert first.media_version == second.media_version
    assert first.frames[0].ocr.fingerprint != second.frames[0].ocr.fingerprint
    assert tools.count("ffmpeg") == 3 and tools.count("tesseract") == 2


async def test_repeated_scene_not_removed_and_different_colours_not_collapsed(media):
    source, service, tools = media
    tools.images[:3] = [png("red"), png("blue"), png("red")]
    result = await service.prepare(source, Context())
    assert [f.selected_for_vision for f in result.frames] == [True, True, False]
    assert len(result.frames) == 3 and tools.count("tesseract") == 2


@pytest.mark.parametrize(
    "kind,value,code",
    [
        ("duration", "601", "media_duration_limit"),
        ("duration", "nan", "media_invalid"),
        ("duration", "0", "media_invalid"),
        ("width", 1000000, "media_dimension_limit"),
        ("avg_frame_rate", "0/0", "media_invalid"),
    ],
)
async def test_probe_limits_before_frame_work(media, kind, value, code):
    source, service, tools = media
    if kind == "duration":
        tools.info["format"][kind] = value
    else:
        tools.info["streams"][0][kind] = value
    with pytest.raises(AppError) as error:
        await service.prepare(source, Context())
    assert error.value.code == code
    assert tools.count("ffmpeg") == tools.count("tesseract") == 0


async def test_media_without_video_reports_no_evidence(media):
    source, service, tools = media
    tools.info["streams"] = [dict(codec_type="audio")]
    with pytest.raises(AppError) as error:
        await service.prepare(source, Context())
    assert error.value.code == "media_no_video"


@pytest.mark.parametrize(
    "path,code",
    [
        ("https://youtu.be/dQw4w9WgXcQ", "media_url_unsupported"),
        ("https://user:secret@example.invalid/private", "media_url_unsupported"),
        ("outside.mp4", "media_path_forbidden"),
    ],
)
async def test_reject_remote_or_unstaged_paths_without_network(media, path, code):
    _, service, tools = media
    with pytest.raises(AppError) as error:
        await service.prepare(path, Context())
    assert error.value.code == code
    assert "secret" not in error.value.message and not tools.calls


async def test_big_or_empty_file_and_unsupported_container(media):
    source, service, tools = media
    service.settings.max_input_bytes = 1024
    for data in (b"", b"x" * 1025):
        source.write_bytes(data)
        with pytest.raises(AppError) as error:
            await service.prepare(source, Context())
        assert error.value.code == "media_size_limit"
    source = source.with_suffix(".m3u8")
    source.write_text("https://remote.invalid/segment")
    with pytest.raises(AppError) as error:
        await service.prepare(source, Context())
    assert error.value.code == "media_type_unsupported" and not tools.calls


async def test_permissions_checked_before_cache_and_disabled_by_default(media):
    source, service, tools = media
    await service.prepare(source, Context())
    previous = len(tools.calls)
    context = Context()
    context.cancelled = True
    with pytest.raises(AppError):
        await service.prepare(source, context)
    assert len(tools.calls) == previous
    service.settings.enabled = False
    with pytest.raises(AppError) as error:
        await service.prepare(source, Context())
    assert error.value.code == "media_not_enabled"


async def test_corrupted_asset_cannot_be_served_from_checkpoint(media):
    source, service, _ = media
    result = await service.prepare(source, Context())
    (service.settings.work_root / result.frames[0].asset_key).write_bytes(b"corrupt")
    with pytest.raises(AppError) as error:
        await service.prepare(source, Context())
    assert error.value.code == "media_checkpoint_invalid"


async def test_cross_instance_writer_lock_refuses_duplicate_work(media):
    source, service, tools = media
    result = await service.prepare(source, Context())
    lock = service._lock(service.settings.work_root / result.media_version)
    try:
        with pytest.raises(AppError) as error:
            await MediaPreparation(service.settings, tools=tools).prepare(source, Context())
        assert error.value.code == "media_busy"
    finally:
        lock.close()


async def test_frame_budget_and_original_decoded_pts(media):
    source, service, tools = media
    service.settings.max_frames = 2
    result = await service.prepare(source, Context())
    assert len(result.frames) == 2
    assert all(f.timestamp_basis == "decoded_stream_pts" for f in result.frames)


async def test_invalid_png_is_not_evidence(media):
    source, service, tools = media
    tools.images = [b"broken"] * 3
    with pytest.raises(AppError) as error:
        await service.prepare(source, Context())
    assert error.value.code == "media_invalid_frame"


async def test_input_content_change_has_new_media_version(media):
    source, service, _ = media
    first = await service.prepare(source, Context())
    source.write_bytes(b"changed fixture")
    second = await service.prepare(source, Context())
    assert second.media_version != first.media_version


async def test_close_rejects_work(media):
    source, service, _ = media
    await service.close()
    with pytest.raises(AppError) as error:
        await service.prepare(source, Context())
    assert error.value.code == "media_closed"


async def test_service_and_adapter_handoff_does_not_refetch_captions(media, config):
    from youtube_ingestion.integration import IngestionAdapters
    from youtube_ingestion.service import IngestionService

    source, prepared, _ = media

    class NoCaptionCalls:
        async def fetch(self, *args):
            pytest.fail("Local media must not re-fetch transcripts or call a provider")

        async def close(self):
            pass

    service = IngestionService(
        config, captions=NoCaptionCalls(), metadata=NoCaptionCalls(), media=prepared
    )
    adapters = IngestionAdapters(service, NoCaptionCalls())
    result = await adapters.prepare_media(source, Context())
    assert result.kind == "media"
    await adapters.close()
    assert prepared.closed


async def test_ocr_failure_keeps_image_and_does_not_fabricate_text(media):
    source, service, tools = media
    original = tools.run

    async def broken_ocr(command, context, **kwargs):
        if command[0] == "tesseract" and "--version" not in command:
            return b"malformed TSV"
        return await original(command, context, **kwargs)

    tools.run = broken_ocr
    result = await service.prepare(source, Context())
    assert result.frames[0].ocr.reason == "ocr_invalid_output"
    assert result.frames[0].ocr.text == ""
    assert (service.settings.work_root / result.frames[0].asset_key).is_file()
    before = tools.count("ffmpeg")
    tools.run = original
    retried = await service.prepare(source, Context())
    assert retried.frames[0].ocr.status == "ready"
    assert tools.count("ffmpeg") == before
