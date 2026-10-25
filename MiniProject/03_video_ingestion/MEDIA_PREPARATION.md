# Local media and OCR preparation — module 03

Status (2026-10-24): working, tested local preparation; **not a public upload or
captionless-import API**. Base develop is 1814bf3. The supplied 00_OVERVIEW (1).md
and 03_VIDEO_INGESTION.md were read fully. 02 currently has no agreed media/evidence
snapshot contract, upload staging or image-authorization endpoint. This change stays
inside 03 and does not create a fake transcript to fit the existing Source schema.

## Server-side handoff

`await MediaPreparation(settings).prepare(staged_path, execution_context)` returns
`PreparedMedia`, never `TranscriptResult`. `IngestionService.prepare_media` and
`IngestionAdapters.prepare_media` delegate to this same implementation. The latter
is an internal method, not a newly advertised capability or an HTTP route. The
existing transcript worker and all caption failure codes remain unchanged.

Before wiring, 02 must authorize a job's specific uploaded object, enforce size/MIME
on upload, stage an immutable regular file in MEDIA_UPLOAD_ROOT, and pass only its
server-resolved path plus a live ExecutionContext. Never accept a client filesystem
path or use a guessed user_id as authority. Context checks run before any work/cache
read, during copying/tool execution and before checkpoint/result publication.

Remote URLs (including YouTube), paths outside the upload root and unsupported
containers are rejected explicitly. No downloader, cookies, proxy rotation or login
bypass is implemented. The supported handoff is a local MP4/MOV/M4V/MKV/WebM/AVI;
02 must provide the lawful-upload alternative at its API layer. ffprobe verifies the
container, video stream, duration, dimensions and audio/subtitle presence. Format and
protocol whitelists exclude HLS/playlists and network protocols. A subtitle stream
flag does not claim its text was read.

## Sampling and artifacts

- Default: at most 600 seconds, 256 MiB input, 12 sampled occurrences, 60-second target
  spacing, 8,294,400 source pixels and 16 MiB per decoded PNG. These are local design
  ceilings, not Google quotas. No Gemini request or client is created by this path.
- Sampling uses uniform midpoint targets, not semantic scene detection. Actual frame
  times are obtained from FFmpeg showinfo PTS with copyts and normalized to media start;
  seek_timestamp_seconds is retained separately. Missing/invalid PTS fails explicitly.
- Keep full-resolution sampled PNGs without resizing them into evidence thumbnails.
  SHA-256 identifies each PNG; frame_id also binds media_version and actual timestamp.
  Exact PNG duplicates share one stored asset/OCR result but retain every timestamp.
- Perceptual grayscale hash plus mean colour marks near duplicates for the future
  vision candidate list. This heuristic can be wrong: all sampled occurrences and
  their original PNGs remain available. Near matches do not reuse OCR unless image
  hashes are identical. A later recurrence is not erased from the timeline.
- Coverage lists sampled points and all intervening unsampled intervals. A still image
  proves a point observation; it does not establish that a whole scene/bin was watched.
  whole_video_reviewed is always false. Brief events can be missed.

The internal result includes media_version, source SHA-256, media properties, decoder
version, frames with private relative asset_key, OCR, coverage and stored_image_bytes.
The byte count covers unique stored PNGs, not the whole cache/upload directory. OCR
and visual_analysis=not_requested are separate. Nothing guesses missing products,
identifies faces/voices or creates unheard speech/lyrics.

## Local OCR

07 supplies FFmpeg/ffprobe, Tesseract and trusted tha/eng traineddata. Set
MEDIA_TESSDATA_DIR explicitly; no automatic engine/model install or cloud OCR occurs.
OCR uses tha+eng and sparse-text segmentation, returning engine/version, language/model
fingerprint, text, word boxes and available confidence on Tesseract's 0–100 scale.
Confidence is engine output, not a calibrated guarantee. Thai spacing/recognition can
be imperfect; original PNGs remain the review source.

A missing engine/model yields unavailable with its reason and keeps images. No text
is empty, not proof that objects are absent. Malformed TSV or a failed OCR process is
unavailable, not successful empty OCR. Timeout/cancellation remains a task failure.
Failed OCR can retry without frame extraction; model/engine changes refresh OCR while
reusing unchanged frame artifacts. Explicit engine parameters avoid relying on an
external tsv config file being bundled with the traineddata directory.

## Checkpoints, cancellation and limits

A source snapshot is copied into an isolated temporary directory with a streaming
size cap/hash. The media cache version binds source hash, decoder/Pillow versions,
sampling policy/targets and duplicate threshold. OCR has a separate engine/model hash.
A nonblocking OS file lock prevents two writers for that version, including across
processes; OS process exit releases it. Versioned checkpoints use atomic replacement.
Resume validates every committed image hash and private relative asset key. Tampered
checkpoints fail closed; completed work is not silently trusted or overwritten.

Cancellation, tool failure and normal completion remove the owned input snapshot and
uncommitted image/JSON partials. Completed checkpoints are retained for resume, never
recursively deleted on a member cancel. The original uploaded file belongs to 02 and
is not deleted by 03. Cache retention/reference-safe GC and a global disk quota must
be agreed with 02/07 before public activation.

Each local-tool process tree runs through a separate resource launcher with one OCR/
decoder thread, a per-tool deadline and bounded stdout/stderr. Windows uses a Job
Object for committed memory, total job CPU time and kill-on-close descendants. POSIX
uses address-space/CPU rlimits and process-group cleanup. If limits cannot be installed,
execution fails closed. Cleanup has a separate 2.5-second drain budget; failure closes
the transport and reports media_cleanup_timeout. Shutdown cancels and joins local work.
Parent image decoding/copying is bounded by pixel/byte limits; 07 still owns worker-wide
container/OS resource isolation. This Windows run does not certify Linux/container limits.

## Configuration and tests

MEDIA_ENABLED defaults false and does not enable a route. MediaSettings is separate
from IngestionSettings so 02's existing full-launcher field mapping is preserved.
See .env.example for local-only settings. The normal live caption/RAG factory still
has its own provider requirements; do not start it merely to perform local preparation.
No LLM_MODEL, billing, provider tier or quota configuration is changed here.

From MiniProject with installed local tools and a Thai/English font:

```powershell
uv sync --project 03_video_ingestion --locked
$env:MEDIA_TEST_TOOLS = (Resolve-Path runtime/media-tools).Path
# Optional: MEDIA_TEST_FONT points to an installed Thai/English TrueType font.
uv run --project 03_video_ingestion --locked pytest 03_video_ingestion/tests -q -W error
```

The engine test expects ffmpeg.exe, ffprobe.exe, tesseract/tesseract.exe and
`tessdata/{tha,eng}.traineddata` beneath that test root (omit .exe on POSIX). It creates
its own silent clip; it does not download arbitrary media or contact providers. If
the opt-in variable is absent, two engine acceptance cases explicitly skip; do not
count those skips as successful real OCR validation. Unit/process tests still run.

## Upstream release gates

02 must define evidence kinds/versions, durable media jobs and authorized image APIs,
then route no_transcript to preparation without manufacturing TranscriptResult. Existing
ready transcripts must be reused, never re-fetched because a later vision/embedding
request hits 429/503. 04 must index/search OCR and media snapshots with membership and
generation fences. 05 receives selected frames through 02's quota broker, never a
03-created Gemini client. No visual broker/LLM requests are implemented here.

07 must package/pin engines and models, refresh consumer locks for the added Pillow
dependency, validate Linux/container isolation, storage retention and end-to-end
captionless imports. Google Free Tier/billing/allowlists and quotas require the joint
02/07 confirmation before any later API path can be activated. This local path needs
no API key and makes no claim to have verified a project's billing tier.

Primary command references: [ffprobe](https://ffmpeg.org/ffprobe.html),
[Tesseract CLI](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html),
[Tesseract installation](https://tesseract-ocr.github.io/tessdoc/Installation.html).

## Integrated Linux engine acceptance (2026-10-25)

The real-engine fixture accepts MEDIA_TEST_FONT for Thai and MEDIA_TEST_LATIN_FONT for Latin glyphs; on Windows both may use Tahoma. On Linux, use installed Noto Thai and Latin fonts separately. Fixture-only FFV1 encoding uses a separate bounded 2GB virtual-address budget; the actual decoding/OCR under test retains the configured product memory limit. This is not an increase to the production default or a general server capacity claim.
