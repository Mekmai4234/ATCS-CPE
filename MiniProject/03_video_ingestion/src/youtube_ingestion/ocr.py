"""Local Thai/English OCR. Empty text is not evidence of absent objects or people."""

import csv
import hashlib
import io
import json

from youtube_backend.errors import AppError

from .media_models import OcrResult, OcrWord


class LocalOcr:
    def __init__(self, settings, tools):
        self.settings, self.tools = settings, tools

    async def identity(self, context):
        version, reason = None, None
        models = {}
        try:
            version = (
                (
                    await self.tools.run(
                        [self.settings.tesseract, "--version"], context, max_bytes=8192
                    )
                )
                .decode()
                .splitlines()[0]
            )
            for language in self.settings.ocr_languages.split("+"):
                path = self.settings.tessdata_dir
                model = path / f"{language}.traineddata" if path else None
                if model is None or not model.is_file():
                    reason = "ocr_language_unavailable"
                    break
                # Installed engine/model directory is trusted server configuration (07).
                with model.open("rb") as stream:
                    digest = hashlib.sha256()
                    while block := stream.read(1024 * 1024):
                        context.check()
                        digest.update(block)
                models[language] = digest.hexdigest()
        except AppError as error:
            if error.code not in {"media_tool_unavailable", "media_tool_failed"}:
                raise
            reason = "ocr_engine_unavailable"
        except (IndexError, UnicodeError):
            reason = "ocr_invalid_engine_output"
        fingerprint = hashlib.sha256(
            json.dumps(
                [version, models, self.settings.ocr_languages, "tsv-psm11-v2", reason],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return dict(
            engine_version=version, fingerprint=fingerprint, languages=self.settings.ocr_languages
        ), reason

    async def recognize(self, path, context, identity, reason):
        if reason:
            return OcrResult(**identity, status="unavailable", reason=reason)
        try:
            data = await self.tools.run(
                [
                    self.settings.tesseract,
                    path,
                    "stdout",
                    "--tessdata-dir",
                    self.settings.tessdata_dir,
                    "-l",
                    self.settings.ocr_languages,
                    "--psm",
                    "11",
                    "-c",
                    "tessedit_create_tsv=1",
                ],
                context,
            )
            words, lines = [], {}
            rows = csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t")
            if not rows.fieldnames or not {
                "level",
                "text",
                "conf",
                "page_num",
                "block_num",
                "par_num",
                "line_num",
                "left",
                "top",
                "width",
                "height",
            }.issubset(rows.fieldnames):
                raise ValueError("Invalid TSV header")
            for row in rows:
                if row["level"] != "5" or not row["text"].strip():
                    continue
                word = OcrWord(
                    text=row["text"],
                    confidence=float(row["conf"]),
                    **{key: int(row[key]) for key in ("left", "top", "width", "height")},
                )
                words.append(word)
                key = tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
                lines.setdefault(key, []).append(word.text)
            return OcrResult(
                **identity,
                status="ready" if words else "empty",
                words=words,
                text="\n".join(" ".join(line) for line in lines.values()),
            )
        except AppError as error:
            if error.code not in {"media_tool_failed", "media_tool_output_limit"}:
                raise
            return OcrResult(**identity, status="unavailable", reason="ocr_failed")
        except (ValueError, KeyError, UnicodeError, TypeError, AttributeError):
            return OcrResult(**identity, status="unavailable", reason="ocr_invalid_output")
