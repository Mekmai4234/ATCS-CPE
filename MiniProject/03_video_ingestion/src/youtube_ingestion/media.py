"""Opt-in local media preparation; no Gemini, URL downloader or fake transcripts."""

import asyncio
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
import warnings
from fractions import Fraction
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from PIL import __version__ as pillow_version
from pydantic import ValidationError

from .config import MediaSettings
from .errors import failure
from .local_tools import LocalTools
from .media_models import MediaFrame, MediaInfo, PreparedMedia, SamplingCoverage
from .ocr import LocalOcr

FORMATS = "mov,matroska,avi"
EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def schedule(info, settings):
    count = min(
        settings.max_frames,
        max(1, math.ceil(info.duration_seconds / settings.sample_interval_seconds)),
    )
    return [round((i + 0.5) * info.duration_seconds / count, 6) for i in range(count)]


def coverage(info, timestamps):
    # A still frame proves a point observation, not that its whole sampling bin was seen.
    intervals = [(t, t) for t in timestamps]
    unseen, end = [], 0.0
    for start, stop in intervals:
        if start > end:
            unseen.append((end, start))
        end = max(end, stop)
    if end < info.duration_seconds:
        unseen.append((end, info.duration_seconds))
    return SamplingCoverage(
        sampled_timestamps=timestamps, inspected_intervals=intervals, unsampled_intervals=unseen
    )


class MediaPreparation:
    def __init__(self, settings=None, *, tools=None):
        self.settings = settings or MediaSettings()
        self.tools = tools or LocalTools(self.settings)
        self.ocr = LocalOcr(self.settings, self.tools)
        self.tasks = set()
        self.closed = False

    async def _snapshot(self, path, directory, context):
        if not isinstance(path, (str, Path)) or "://" in str(path):
            raise failure(
                "media_url_unsupported",
                "Stage an authorized upload through 02; remote media URLs are unsupported",
                422,
            )
        root = self.settings.upload_root.resolve()
        source = Path(path).resolve()
        if not source.is_relative_to(root) or source == root:
            raise failure(
                "media_path_forbidden", "Media must be inside the server upload root", 403
            )
        if source.suffix.lower() not in EXTENSIONS:
            raise failure("media_type_unsupported", "Unsupported local video container", 422)
        if not source.is_file():
            raise failure("media_not_found", "Staged video is unavailable", 404)
        size = source.stat().st_size
        if not 0 < size <= self.settings.max_input_bytes:
            raise failure(
                "media_size_limit", "Video exceeds the local input limit or is empty", 422
            )
        target = directory / ("input" + source.suffix.lower())
        hashed, copied = hashlib.sha256(), 0
        with source.open("rb") as incoming, target.open("wb") as outgoing:
            while block := incoming.read(1024 * 1024):
                context.check()
                copied += len(block)
                if copied > self.settings.max_input_bytes:
                    raise failure("media_size_limit", "Video exceeded the input limit", 422)
                hashed.update(block)
                outgoing.write(block)
                await asyncio.sleep(0)
        if copied != size:
            raise failure("media_source_changed", "Staged video changed while reading", 409, True)
        return target, copied, hashed.hexdigest()

    async def _probe(self, path, size, context):
        data = await self.tools.run(
            [
                self.settings.ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                FORMATS,
                "-show_entries",
                "format=duration,start_time:stream=index,codec_type,width,height,avg_frame_rate:stream_disposition=attached_pic",
                "-of",
                "json",
                path,
            ],
            context,
        )
        try:
            probe = json.loads(data)
            streams = probe["streams"]
            if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
                raise ValueError("Invalid stream list")
            videos = [
                s
                for s in streams
                if s.get("codec_type") == "video"
                and not s.get("disposition", {}).get("attached_pic")
            ]
            if not videos:
                raise failure("media_no_video", "Media has no readable video stream", 422)
            video = videos[0]
            info = MediaInfo(
                duration_seconds=float(probe["format"]["duration"]),
                size_bytes=size,
                start_time_seconds=float(probe["format"].get("start_time", 0)),
                width=video["width"],
                height=video["height"],
                video_stream_index=video["index"],
                fps=float(Fraction(video["avg_frame_rate"])),
                has_audio=any(s.get("codec_type") == "audio" for s in streams),
                has_subtitle_stream=any(s.get("codec_type") == "subtitle" for s in streams),
            )
        except (ValueError, KeyError, TypeError, ZeroDivisionError, ValidationError):
            raise failure(
                "media_invalid", "Cannot validate media duration or streams", 422
            ) from None
        if info.duration_seconds > self.settings.max_duration_seconds:
            raise failure("media_duration_limit", "Video exceeds the duration limit", 422)
        if info.width * info.height > self.settings.max_pixels:
            raise failure("media_dimension_limit", "Video dimensions exceed the local limit", 422)
        return info

    @staticmethod
    def _lock(folder):
        stream = (folder / "writer.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if not stream.seek(0, 2):
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise failure("media_busy", "This media is already being prepared", 409, True) from None
        return stream

    def _image(self, data):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(io.BytesIO(data))
            if image.format != "PNG" or image.width * image.height > self.settings.max_pixels:
                raise ValueError
            image.load()
            pixels = list(image.convert("L").resize((8, 8)).tobytes())
            average = sum(pixels) / 64
            colour = image.convert("RGB").resize((1, 1)).getpixel((0, 0))
            return (
                f"{sum((v > average) << i for i, v in enumerate(pixels)):016x}"
                + bytes(colour).hex()
            )
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise failure(
                "media_invalid_frame", "Decoder did not produce a valid bounded PNG", 422
            ) from None

    def _restore(self, folder, version, timestamps):
        path = folder / "checkpoint.json"
        if not path.exists():
            return []
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
            if checkpoint["media_version"] != version:
                raise ValueError
            frames = [MediaFrame.model_validate(f) for f in checkpoint["frames"]]
            if len(frames) > len(timestamps):
                raise ValueError
            for i, frame in enumerate(frames):
                asset = folder / (frame.sha256 + ".png")
                if (
                    frame.seek_timestamp_seconds != timestamps[i]
                    or frame.asset_key != f"{version}/{asset.name}"
                    or asset.is_symlink()
                    or asset.stat().st_size > self.settings.max_frame_bytes
                    or digest(asset.read_bytes()) != frame.sha256
                ):
                    raise ValueError
            return frames
        except (ValueError, KeyError, TypeError, OSError, ValidationError):
            raise failure(
                "media_checkpoint_invalid", "Private media checkpoint failed integrity checks", 409
            ) from None

    @staticmethod
    def _save(folder, version, frames):
        temporary = folder / "checkpoint.partial"
        temporary.write_text(
            json.dumps(
                dict(media_version=version, frames=[f.model_dump() for f in frames]),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(folder / "checkpoint.json")

    async def prepare(self, path, context):
        context.check()
        if not self.settings.enabled:
            raise failure("media_not_enabled", "Local media preparation is disabled", 503)
        if self.closed:
            raise failure("media_closed", "Local media adapter is closed", 503)
        task = asyncio.current_task()
        root = self.settings.work_root.resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        scratch = Path(tempfile.mkdtemp(prefix="preparing-", dir=root)).resolve()
        self.tasks.add(task)
        lock, folder = None, None
        try:
            async with asyncio.timeout(
                min(self.settings.total_timeout_seconds, context.remaining_seconds)
            ):
                snapshot, size, source_hash = await self._snapshot(path, scratch, context)
                info = await self._probe(snapshot, size, context)
                engine = (
                    (
                        await self.tools.run(
                            [self.settings.ffmpeg, "-version"], context, max_bytes=16384
                        )
                    )
                    .decode()
                    .splitlines()[0]
                )
                timestamps = schedule(info, self.settings)
                version = digest(
                    json.dumps(
                        [
                            "media03-v1",
                            pillow_version,
                            source_hash,
                            engine,
                            timestamps,
                            self.settings.near_duplicate_distance,
                        ]
                    ).encode()
                )
                folder = root / version
                if folder.is_symlink():
                    raise failure("media_checkpoint_invalid", "Private cache path is invalid", 409)
                folder.mkdir(exist_ok=True, mode=0o700)
                lock = self._lock(folder)
                frames = self._restore(folder, version, timestamps)
                identity, reason = await self.ocr.identity(context)
                reused = {}
                for frame in frames:
                    context.check()
                    if frame.ocr.fingerprint != identity["fingerprint"] or (
                        frame.ocr.status == "unavailable"
                        and frame.ocr.reason in {"ocr_failed", "ocr_invalid_output"}
                    ):
                        frame.ocr = reused.get(frame.sha256) or await self.ocr.recognize(
                            root / frame.asset_key, context, identity, reason
                        )
                    reused[frame.sha256] = frame.ocr
                self._save(folder, version, frames)
                for timestamp in timestamps[len(frames) :]:
                    context.check()
                    data, diagnostics = await self.tools.run(
                        [
                            self.settings.ffmpeg,
                            "-nostdin",
                            "-v",
                            "info",
                            "-protocol_whitelist",
                            "file,pipe",
                            "-format_whitelist",
                            FORMATS,
                            "-threads",
                            "1",
                            "-filter_threads",
                            "1",
                            "-copyts",
                            "-ss",
                            str(timestamp),
                            "-i",
                            snapshot,
                            "-map",
                            f"0:{info.video_stream_index}",
                            "-vf",
                            "showinfo",
                            "-frames:v",
                            "1",
                            "-an",
                            "-sn",
                            "-c:v",
                            "png",
                            "-threads",
                            "1",
                            "-f",
                            "image2pipe",
                            "pipe:1",
                        ],
                        context,
                        max_bytes=self.settings.max_frame_bytes,
                        capture_stderr=True,
                    )
                    match = re.search(rb"\bn:\s*0\s+.*?pts_time:\s*([-+0-9.eE]+)", diagnostics)
                    if match is None:
                        raise failure(
                            "media_timestamp_unavailable",
                            "Decoder returned no frame timestamp",
                            422,
                        )
                    actual = float(match[1]) - info.start_time_seconds
                    if (
                        not math.isfinite(actual)
                        or not timestamp - 0.001 <= actual <= info.duration_seconds
                    ):
                        raise failure(
                            "media_invalid_timestamp",
                            "Decoded frame timestamp is outside the requested media interval",
                            422,
                        )
                    visual_hash, image_hash = self._image(data), digest(data)
                    asset = folder / f"{image_hash}.png"
                    if asset.is_symlink():
                        raise failure(
                            "media_checkpoint_invalid", "Private asset path is invalid", 409
                        )
                    if not asset.exists():
                        # Completed assets are immutable; no unbounded decoder disk output.
                        partial = folder / f"{image_hash}.partial"
                        partial.write_bytes(data)
                        partial.replace(asset)
                    elif (
                        asset.stat().st_size > self.settings.max_frame_bytes
                        or digest(asset.read_bytes()) != image_hash
                    ):
                        # This asset is not in the restored checkpoint; repair an interrupted write.
                        partial = folder / f"{image_hash}.partial"
                        partial.write_bytes(data)
                        partial.replace(asset)
                    ocr = reused.get(image_hash)
                    if ocr is None:
                        ocr = await self.ocr.recognize(asset, context, identity, reason)
                        reused[image_hash] = ocr
                    similar = next(
                        (f for f in frames if self._similar(f.perceptual_hash, visual_hash)), None
                    )
                    frame = MediaFrame(
                        frame_id=digest(f"{version}:{actual}:{image_hash}".encode()),
                        timestamp_seconds=actual,
                        seek_timestamp_seconds=timestamp,
                        sha256=image_hash,
                        asset_key=f"{version}/{image_hash}.png",
                        perceptual_hash=visual_hash,
                        near_duplicate_of=similar.frame_id if similar else None,
                        selected_for_vision=similar is None,
                        ocr=ocr,
                    )
                    frames.append(frame)
                    context.check()
                    self._save(folder, version, frames)
                context.check()
                return PreparedMedia(
                    media_version=version,
                    source_sha256=source_hash,
                    extraction_engine=engine,
                    info=info,
                    frames=frames,
                    stored_image_bytes=sum(
                        (folder / f"{h}.png").stat().st_size for h in {f.sha256 for f in frames}
                    ),
                    coverage=coverage(info, [f.timestamp_seconds for f in frames]),
                )
        except TimeoutError:
            raise failure(
                "media_timeout", "Local preparation exceeded its deadline", 504, True
            ) from None
        finally:
            if lock is not None:
                # Remove only incomplete scratch data; completed checkpoints survive cancellation.
                (folder / "checkpoint.partial").unlink(missing_ok=True)
                for partial in folder.glob("*.partial"):
                    if re.fullmatch(r"[a-f0-9]{64}\.partial", partial.name):
                        partial.unlink()
                checkpoint = folder / "checkpoint.json"
                # Under this writer lock, discard images not committed to the last checkpoint.
                # Never remove assets referenced by a completed checkpoint or another writer.
                try:
                    saved = (
                        json.loads(checkpoint.read_text(encoding="utf-8"))
                        if checkpoint.exists()
                        else {"frames": []}
                    )
                    keep = {f["sha256"] + ".png" for f in saved["frames"]}
                    for orphan in folder.glob("*.png"):
                        if orphan.name not in keep and re.fullmatch(
                            r"[a-f0-9]{64}\.png", orphan.name
                        ):
                            orphan.unlink()
                except (OSError, ValueError, KeyError, TypeError):
                    # Corrupt checkpoints fail closed on read; do not guess which assets to delete.
                    pass
                lock.close()
            if scratch.parent == root and scratch.name.startswith("preparing-"):
                shutil.rmtree(scratch)
            self.tasks.discard(task)

    async def close(self):
        self.closed = True
        for task in list(self.tasks - {asyncio.current_task()}):
            task.cancel()
        await asyncio.gather(*list(self.tasks - {asyncio.current_task()}), return_exceptions=True)
        await self.tools.close()

    def _similar(self, left, right):
        return (
            int(left[:16], 16) ^ int(right[:16], 16)
        ).bit_count() <= self.settings.near_duplicate_distance and max(
            abs(a - b)
            for a, b in zip(bytes.fromhex(left[16:]), bytes.fromhex(right[16:]), strict=True)
        ) <= 12
