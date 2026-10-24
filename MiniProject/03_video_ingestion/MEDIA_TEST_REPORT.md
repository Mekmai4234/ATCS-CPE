# Local media/OCR verification — 2026-10-24

Scope: module 03 only, branch codex/03-local-media-ocr from develop 1814bf3.
Read both supplied plans (00_OVERVIEW (1).md and 03_VIDEO_INGESTION.md). No source,
schema, migration, API route or lockfile in another module is changed.

## Delivered

- Opt-in MediaPreparation and internal service/adapter handoff returning PreparedMedia,
  separate from TranscriptResult and disabled by default.
- Authorized-server-staging path boundary, local container/stream/duration/size checks,
  capped midpoint frame selection, actual decoded PTS and explicit unsampled coverage.
- Original PNG hashes/private asset keys, exact-image OCR reuse, near-duplicate candidate
  hints that preserve occurrence times and original images.
- Local Thai/English Tesseract text, boxes, confidence, engine/model fingerprints and
  distinct empty/unavailable states. No OCR failure invents text or removes the image.
- Locked, atomic checkpoints; OCR refresh/retry reuses completed image extraction.
- Process-tree CPU/memory/deadline/output caps; cancel/shutdown cleanup preserves only
  committed work. Windows Job Object limits were tested with actual runaway children.
- Pillow dependency plus 03 uv.lock and English configuration/workflow documentation.

## Validation

Windows / Python 3.11.9, local 02/04 packages from the current develop checkout.

| Check | Observed result | Local evidence |
|---|---|---|
| Complete 03 suite, --locked -q -W error, with engine opt-in | **144 passed**, 74.98 s | runtime/media03-full.xml |
| Final media/engine tests after interrupted-write/parser hardening | **28 passed**, 7.38 s | runtime/media03-final-media.xml |
| Existing full-launcher configuration regression | **29 passed**, 34.15 s | runtime/media03-full-config.xml |
| uv lock --check --offline; uv sync --locked | Passed, 114 resolved packages | command output |
| Ruff lint, formatting and git diff --check | Passed | command output |

The suite retains 107 pre-existing tests and adds 37 media/process/engine cases.
They cover corrupt/empty/oversized/disallowed inputs, missing streams/models, decoded
PTS, duplicates, cache integrity, cross-instance writer exclusion, restart after
cancel/timeout, OCR-only refresh, scope revocation, child/descendant termination,
actual memory/CPU enforcement and the separate caption/media handoff.

The first resource test found an incorrect Windows memory-limit flag; it was fixed
and the actual over-allocation test passes. CPU-limit testing allows OS accounting
wall-time slack while requiring CPU termination, rather than accepting a wall timeout.
The engine test also caught a missing Tesseract tsv config dependency; explicit TSV
output parameters and header validation now distinguish failure from empty text.

The full configuration suite uses its existing full/.venv interpreter directly. It
is not a claim that every downstream --locked environment has been refreshed.
Only 03's lock was updated; 07 owns consumer-lock/container integration.

## Real local-engine acceptance

A self-created, silent 3-second FFV1/MKV video displays English "RAG BUDDY" and Thai
"ทดสอบภาษาไทย" using the installed Tahoma font. No remote media was used.

- Four requested seek targets: 0.375, 1.125, 1.875, 2.625 seconds.
- Actual stored decoder frame times: **0.5, 1.25, 2.0, 2.75** seconds.
- All four occurrences remain; one unique original PNG uses **21,844 bytes**.
- English text was recognized as RAG BUDDY. Thai characters were recognized but split
  into imperfect word/character spacing. This is mechanics evidence, not a Thai OCR
  accuracy benchmark; keep the original image for review.
- OCR reports Tesseract v5.5.3.20260724, word boxes/confidences and model fingerprints.
- Re-preparing the file returns the same version/result. Real corrupt media fails
  promptly and leaves no input scratch directory.

Engine setup was confined to ignored runtime/media-tools for validation; no global
install, PATH mutation or 07 packaging change was made. FFmpeg/ffprobe were taken
from BtbN's 2026-10-23 build; Tesseract from the UB Mannheim installer linked by the
Tesseract project; tha/eng models from tesseract-ocr/tessdata_fast. No binaries/models
are committed. Engine/model SHA-256 values are listed below for this run.

| Artifact | SHA-256 |
|---|---|
| ffmpeg.exe | 6a7f66957267ebe36c087036fa5e3e507c05c3b666416f3b5c2c8ba5de15bf96 |
| ffprobe.exe | 48f1cd294dabce5a889cc97d9f291713efe885beb828389e873cb578dc934ba1 |
| tesseract/tesseract.exe | c66f0f12ed76f6aa455dac97684bbc86756d6a732380bee09122454cfda3f420 |
| tessdata/tha.traineddata | 294227cc2d1292b0acb28d61d4115c88252b96d466ca90b417cf4cf0c67bf07c |
| tessdata/eng.traineddata | 7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2 |

Prepared JSON and a sample original image were copied to ignored local
runtime/media03-evidence/prepared.json and sample.png. Those are synthetic test data,
not real member uploads. No API credentials, OCR text from users or secrets are logged.

Representative commands from MiniProject:

```powershell
uv sync --project 03_video_ingestion --locked
uv lock --check --offline --project 03_video_ingestion
$env:MEDIA_TEST_TOOLS = (Resolve-Path runtime/media-tools).Path
uv run --project 03_video_ingestion --locked pytest 03_video_ingestion/tests -q -W error
```

Without MEDIA_TEST_TOOLS, the two real-engine cases explicitly skip; do not describe
such a run as real OCR acceptance. The recorded 144-pass run enabled both cases.

## Limits and required handoff

This is a working local-preparation component, not working captionless imports on
the website. 02 still needs its media/evidence/job/upload/image-access contract;
04/05 need authorized OCR/vision integration, and 05 calls must use 02's quota broker.
No automatic no_transcript fallback is enabled against the old transcript-only schema.
02 must authorize the actual staged file; a general context.check alone does not
establish which arbitrary file a job may access.

No Google/Gemini/Cloud Vision/OpenAI calls were made, no billing or model/tier was
changed, and no Free Tier eligibility or quota was verified. Existing transcripts
are never fetched by the new local path. Browser-to-backend media E2E, real provider
quality, Linux/Docker limits, engine/model packaging, global storage limits and
reference-safe media-cache GC remain joint 02/04/05/07 release gates. Completed private
artifacts must not be exposed as static public files or deleted on one member's cancel.
