# Module 03 — YouTube Video Ingestion

Live accessible captions and metadata, normalized into 02's strict `TranscriptResult`.
Includes a 03-owned factory for `ingest -> 02 persistence -> 04 index`, offline tests,
real SQLite/Chroma integration tests, and an explicit public YouTube read check.
Existing 02/04/06 source and factories are unchanged.

## Install and test

From **MiniProject root**, with Python >=3.11,<3.14 and uv:

```powershell
uv sync --project 03_video_ingestion --locked
uv run --project 03_video_ingestion --locked pytest 03_video_ingestion/tests -q -W error
uv run --project 03_video_ingestion --locked ruff check 03_video_ingestion
uv run --project 03_video_ingestion --locked ruff format --check 03_video_ingestion
```

The lock installs local packages 02 and 04. Normal tests need no credentials or existing
database. HTTP/embeddings/transcripts are doubles in integration tests; API/worker,
migrations, cancellation, SQLite and Chroma are real. The real caption SDK also runs
against mocked HTTP, and real subprocesses verify timeout/cancellation cleanup.

Explicit live check, without embeddings/generation or application database writes:

```powershell
uv run --project 03_video_ingestion --locked python 03_video_ingestion/scripts/live_check.py --video-id dQw4w9WgXcQ --output runtime/ingestion-check/live-check.json
```

This contacts public YouTube, writing only the optional report. It reports counts,
timestamps/provenance and classified errors without transcript text or keys.
See [TEST_REPORT.md](TEST_REPORT.md) for the observed result and limits.

## Configuration

```powershell
if (-not (Test-Path 03_video_ingestion/.env)) {
    Copy-Item 03_video_ingestion/.env.example 03_video_ingestion/.env
}
```

Enter keys locally; never commit `.env`. Ingestion precedence is process > 03/.env >
root .env > defaults. The factory's RAG precedence is process > 03/.env > 04/.env >
root .env > defaults, allowing the 03 template to override the old OpenAI proposal.
Backend Settings still reads root .env and its existing integration override; it does
not load 03/.env. Set backend variables explicitly in both terminals below.

| Variable | Default / meaning |
|---|---|
| `TRANSCRIPT_LANGUAGES` | `th,en`, ordered exact language codes; regions supported |
| `INGEST_TIMEOUT_SECONDS` | 30, entire attempt including metadata/process startup |
| `METADATA_TIMEOUT_SECONDS` | 5, also capped at one quarter of the attempt budget |
| `METADATA_PROVIDER` | `auto`: Data API with key, otherwise oEmbed; also `none` |
| `YOUTUBE_API_KEY` | Optional server-side metadata key |
| `ENABLE_TRANSCRIPTION_FALLBACK` | false; true rejected because ASR is not implemented |
| `GEMINI_API_KEY` | Required only for real 04 embeddings through the live factory |

Language priority comes first, then manual before generated in that language. With
`th,en`, Thai generated captions beat English manual captions. No implicit translation
or unrelated-language fallback occurs; no matching track is `no_transcript`.

oEmbed supplies available title/author/thumbnail. A stable channel ID is retained only
from an explicit `/channel/UC...` URL. Handles never become guessed IDs. Publication
date stays null. Data API videos.list snippet provides channel ID and UTC publication
date; its key travels in a header. Metadata failure logs a classified warning and leaves
fields null while keeping good captions. Missing IDs/dates cannot satisfy 02's filters.
The Data API path has HTTP mock coverage, not live-key verification.

## Run 02 + 03 + 04

Set `GEMINI_API_KEY` in 03/.env for real Gemini embeddings. The factory requires the live
profile and Gemini embeddings; it cannot silently substitute fixture vectors. Use a
dedicated database/index pair, separate from the existing fixture/demo database.

Terminal 1, from MiniProject:

```powershell
$env:ADAPTER_MODE = "custom"
$env:ADAPTER_FACTORY = "youtube_ingestion.integration:create_adapters"
$env:BACKEND_INTEGRATION_PROFILE = "live"
$env:DATABASE_URL = "sqlite:///./runtime/ingestion-live/app.db"
uv run --project 03_video_ingestion --locked yk-db upgrade head
uv run --project 03_video_ingestion --locked yk-rag init
uv run --project 03_video_ingestion --locked yk-api
```

Terminal 2: set the **same four variables**, then:

```powershell
uv run --project 03_video_ingestion --locked yk-worker
```

Open [Swagger](http://127.0.0.1:8000/docs). Submit `POST /api/videos/import` with
`{"urls":["https://youtu.be/dQw4w9WgXcQ"]}` and poll `GET /api/jobs/{job_id}`.
Read `GET /api/videos/{video_id}/transcript`. Only successful verified indexing makes
a clip `ready`. Existing deletion API cleans transcripts and vectors durably.

The factory enables ingest/index/delete/evidence/inventory. Answer/analysis/research/
artifacts remain explicitly unavailable through this factory. It does not implement 05
or replace 02's separate 04/06 factory. Future team composition can delegate `ingest`
to `IngestionService` while retaining other services. Root Compose does not package 03;
these instructions use the local 03 environment, not the root backend-only image.

## Contract and behavior

`await ingestion.ingest(video_id, context)` returns existing 02 `TranscriptResult`.
02 owns URL parsing, deduplication, jobs, transcript storage/hash/version/retries and
the call to 04. 03 validates ID/ownership/deadline and returns metadata, language,
source and segments; it never writes application tables, indexes directly or marks ready.

Each segment has deterministic unique ID, normalized whitespace, original start and
duration. Equal-start order and overlaps are retained; blank segments are omitted.
Invalid/nonfinite/zero-duration intervals fail explicitly; no timestamps are guessed.
`source` distinguishes `youtube_captions:manual` and `youtube_captions:generated`.

The synchronous SDK runs in one killable subprocess per request. Parent timeout,
cancellation, lost job ownership and shutdown kill/reap it. Job ownership is checked
at least every 0.1 seconds while waiting for captions; metadata has a short separate
budget. No uncancellable fetch threads or internal retry loops are used. Child provider
credentials are stripped, stderr discarded, and output bounded to 8 MiB/100,000 segments.
Caption text remains untrusted data, never tool instructions.

| Error | Retry by 02? |
|---|---|
| `no_transcript` | no; completed inspection / no_transcript |
| `video_unavailable`, `video_restricted` | no |
| `youtube_access_blocked` (including IP blocks) | no automatic retry |
| `youtube_rate_limited`, `caption_provider_transient` | yes, bounded |
| `ingest_timeout`, `ingest_unavailable` | yes, bounded |
| `invalid_transcript`, `caption_provider_error` | no |

Unknown errors are redacted; no raw provider messages or credentials are returned/logged.
YouTube can block public caption access. A block is not treated as missing captions.
There is no proxy rotation, cookie authentication or automatic transcription fallback.
No discovery, scheduler, ready-video refresh, ASR, visual understanding or new ownership
model is implemented. The application retains 02's single-user prototype constraints.
Full live ingestion with paid Gemini indexing has not been tested without a key.

References: [caption SDK](https://github.com/jdepoix/youtube-transcript-api),
[YouTube videos.list](https://developers.google.com/youtube/v3/docs/videos/list),
[video snippet fields](https://developers.google.com/youtube/v3/docs/videos).
