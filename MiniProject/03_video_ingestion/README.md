# Module 03 — YouTube Video Ingestion

Live accessible captions and metadata, normalized into 02's strict `TranscriptResult`.
Includes a 03-owned factory for `ingest -> 02 persistence -> 04 index`, offline tests,
real SQLite/Chroma integration tests, and an explicit public YouTube read check.
Existing 02/04/06 source and factories are unchanged.

The 2026-10-24 local media/OCR work is documented in
[MEDIA_PREPARATION.md](MEDIA_PREPARATION.md) and [MEDIA_TEST_REPORT.md](MEDIA_TEST_REPORT.md).
It is an opt-in internal preparation service with real local-engine tests. It does
not yet enable video uploads or captionless imports through the web/API: those need
02's new evidence contract and 04/05 integration. It creates no Gemini client or
fake TranscriptResult and leaves the existing caption worker unchanged.

Member ingestion now uses **02's native session/ownership flow and 04's authorized
ExecutionContext**. The previous proposal-only backend and grants were removed.
This requires the dependency branches/commits listed in [MEMBER_CONTRACT.md](MEMBER_CONTRACT.md);
base develop does not yet include those PRs. See [MEMBER_REPORT.md](MEMBER_REPORT.md)
for review fixes, actual test results and remaining release gates.

## Install and test

From **MiniProject root**, with Python >=3.11,<3.14 and uv:

```powershell
uv sync --project 03_video_ingestion --locked
uv run --project 03_video_ingestion --locked pytest 03_video_ingestion/tests -q -W error
uv run --project 03_video_ingestion --locked ruff check 03_video_ingestion
uv run --project 03_video_ingestion --locked ruff format --check 03_video_ingestion
```

The lock installs local packages 02 and 04 from the documented native dependency
candidate. Normal tests need no credentials or existing database. Google verification,
embeddings and transcript providers are doubles; HTTP API/worker,
migrations, cancellation, SQLite and Chroma are real. The real caption SDK also runs
against mocked HTTP, and real subprocesses verify timeout/cancellation cleanup.

Explicit live check, without embeddings/generation or application database writes:

```powershell
uv run --project 03_video_ingestion --locked python 03_video_ingestion/scripts/live_check.py --video-id dQw4w9WgXcQ --output runtime/ingestion-check/live-check.json
```

This contacts public YouTube, writing only the optional report. It reports counts,
timestamps/provenance and classified errors without transcript text or keys.
See [TEST_REPORT.md](TEST_REPORT.md) for the observed result and limits.
The subprocess cleanup fix and the 2026-10-20 acceptance results are recorded in
[FOLLOWUP_REPORT.md](FOLLOWUP_REPORT.md).

To check real captions through the actual API/worker, transcript persistence and
Chroma indexing without paid embeddings, use a new isolated directory:

```powershell
$ingestionCheckState = "runtime/ingestion-acceptance-$(Get-Date -Format yyyyMMdd-HHmmss)"
uv run --project 03_video_ingestion --locked python 03_video_ingestion/scripts/acceptance_check.py --state $ingestionCheckState --video-id wD3NSzYtsMc --video-id dQw4w9WgXcQ --fixture-identity --fixture-embeddings
```

This explicitly uses real YouTube captions/oEmbed with **fixture embedding values**,
a labelled fixture Google verifier, real session/cookie/CSRF, SQLite/Chroma and
in-process HTTP. It verifies all stored segment timestamps
against provider output and checks that duplicate URLs reuse the same job without
another caption request. Existing nonempty directories are rejected. Its database
has an acceptance-only identity and cannot be reused by the production live factory.
The result checks mechanics. It does not verify real Google login or semantic retrieval/model quality.

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
$env:ADAPTER_FACTORY = "youtube_ingestion.member_adapters:create_member_adapters"
$env:AUTH_ENABLED = "true"
$env:BACKEND_INTEGRATION_PROFILE = "live"
$env:DATABASE_URL = "sqlite:///./runtime/ingestion-live/app.db"
uv run --project 03_video_ingestion --locked yk-db upgrade head
uv run --project 03_video_ingestion --locked yk-rag init
uv run --project 03_video_ingestion --locked yk-api
```

Configure 02 Google client ID, trusted web origins, session signing/cookie settings in
both terminals as required by 02. Production requires HTTPS and Secure cookies.

Terminal 2: set the **same backend variables**, then:

```powershell
uv run --project 03_video_ingestion --locked yk-worker
```

Sign in through 02's challenge/Google exchange using the configured web origin. Send
the session cookie and X-CSRF-Token for mutations; anonymous imports return 401.
Open [Swagger](http://127.0.0.1:8000/docs). Submit `POST /api/videos/import` with
`{"urls":["https://youtu.be/dQw4w9WgXcQ"]}` and poll `GET /api/jobs/{job_id}`.
Read `GET /api/videos/{video_id}/transcript`. Only successful verified indexing makes
a clip `ready`. Deletion detaches the current member; physical GC runs only after the
last reference and active dependency are gone. Shared import cancellation returns 409;
use detach to preserve another member's required work.

The factory enables ingest/index/delete/evidence/inventory. Answer/analysis/research/
artifacts remain explicitly unavailable through this factory. It does not implement 05
or replace 02's separate 04/06 factory. Future team composition can delegate `ingest`
to `IngestionService` while retaining other services. Root Compose does not package 03;
these instructions use the local 03 environment. The separate 03 image uses its own lock:

```powershell
docker build -f 03_video_ingestion/Dockerfile -t ingestion03-native .
```

Build from a candidate with native 02/04 installed. The image runs as a non-root user,
ships no .env/database/keys, and defaults to authenticated native ingestion. Supply
02 auth/origin/HTTPS settings and provider keys at runtime; run migrations and 04 init
explicitly on a dedicated writable DB/index pair. Override CMD with yk-worker for a
worker sharing that pair. Docker build/run could not be verified on this machine
because Docker CLI/Engine are unavailable; deployment acceptance remains pending.

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

Cleanup kills the child **before** draining buffered pipe data and reaping it. Cleanup
has a separate 2-second budget after the fetch attempt; a stalled drain closes the
asyncio process transport, with a further 0.5-second final-reap budget. Thus an attempt
may take its configured timeout plus up to 2.5 seconds of cleanup. Repeated cancellation
cannot abandon this bounded cleanup. Service shutdown cancels/joins all active fetches,
so stdout has only one reader. If final reaping still fails, the adapter closes itself
and returns `ingest_cleanup_timeout` rather than silently starting more children.

| Error | Retry by 02? |
|---|---|
| `no_transcript` | no; completed inspection / no_transcript |
| `video_unavailable`, `video_restricted` | no |
| `youtube_access_blocked` (including IP blocks) | no automatic retry |
| `youtube_rate_limited`, `caption_provider_transient` | yes, bounded |
| `ingest_timeout`, `ingest_unavailable` | yes, bounded |
| `invalid_transcript`, `caption_provider_error` | no |
| `ingest_cleanup_timeout` | no; adapter shuts down for investigation |

Unknown errors are redacted; no raw provider messages or credentials are returned/logged.
YouTube can block public caption access. A block is not treated as missing captions.
There is no proxy rotation, cookie authentication or automatic transcription fallback.
No discovery, scheduler, ready-video refresh, ASR, visual understanding or new ownership
model is implemented in 03. Native membership and job ownership are supplied by 02;
03 does not implement per-member pending/running quotas or fair worker scheduling.
Full live ingestion with paid Gemini indexing has not been tested without a key.

References: [caption SDK](https://github.com/jdepoix/youtube-transcript-api),
[YouTube videos.list](https://developers.google.com/youtube/v3/docs/videos/list),
[video snippet fields](https://developers.google.com/youtube/v3/docs/videos).
