# Module 03 — Implementation and verification

Historical initial implementation results. See [FOLLOWUP_REPORT.md](FOLLOWUP_REPORT.md)
for the 2026-10-20 cleanup fix, new regressions and live acceptance checks.

Verified on 2026-10-19 (Asia/Bangkok). All delivered source, configuration and
documentation changes are confined to `03_video_ingestion`. Verification was completed
before publication. No deployment was performed.

## Results

| Check | Observed result |
|---|---|
| Final module 03 suite, warnings treated as errors | **69 passed**, 18.25 seconds |
| Existing module 02 regression suite, warnings treated as errors | **68 passed**, 19.13 seconds |
| Existing module 04 regression suite, live opt-in disabled, warnings treated as errors | **77 passed, 1 skipped**, 74.91 seconds |
| Ruff lint | Passed |
| Ruff formatting | Passed for Python sources and documentation snippets |
| `uv lock --check` | Passed, 113 locked packages |
| Live public YouTube captions and oEmbed metadata | Passed; observed details below |

The skipped 04 test requires explicit live Gemini opt-in. No Gemini embedding or
generation request was made. Test timings are observations, not application latency
guarantees. Module 06 and Docker were not exercised in this change.

Environment: Windows, Python 3.11.9, uv 0.13.1, youtube-transcript-api 1.2.4,
requests 2.34.2, HTTPX 0.28.1, ChromaDB 1.5.9, google-genai 2.31.0, pytest 9.1.1,
Ruff 0.17.1. Dependencies are pinned in this module's `uv.lock`.

## Implemented

- `youtube_ingestion` package and a local install/test environment.
- Actual public-caption SDK adapter with deterministic language-first selection,
  preferring manual before generated captions within each language.
- Original timing/overlaps, stable unique segment IDs, normalized Unicode whitespace,
  blank-segment removal and strict invalid/nonfinite-interval rejection.
- Manual/generated provenance in the existing backend `source` field.
- Optional oEmbed or YouTube Data API metadata, with absent fields left null and
  separate redacted diagnostics when metadata fails.
- A killable caption subprocess, per-request and overall deadlines, execution-context
  checks, cancellation cleanup, bounded output and credential stripping.
- Classified permanent/access errors and bounded-retry-eligible transport/rate-limit
  errors. Actual SDK HTTP tests verify that HTTP 429 survives the SDK's default
  IpBlocked conversion; player-reported access blocks remain distinct.
- A 03-owned async factory integrating ingestion with the unchanged 02 API/worker
  and unchanged 04 index/evidence/delete implementation. Live configuration requires
  Gemini embeddings and refuses the existing offline demonstration profile.
- Configuration example, runnable instructions, live-check script and updated
  env/workflow/process documents.

## Test coverage and isolation

Unit checks cover preferred languages, manual/generated ordering, stable segments,
duplicates, Thai/English text, overlapping timestamps, empty/malformed transcripts,
invalid configuration, URL/ID rejection, source identity, classified errors, metadata
degradation, timeouts and cancellation. Caption text containing instructions remains
ordinary data. HTTP metadata tests cover missing dates/IDs, wrong videos, invalid
responses, redirects, transport errors, key redaction and client ownership.

Actual youtube-transcript-api code parses mocked watch/player/caption HTTP responses,
including Thai XML, and classifies 429/503/403 without exposing upstream text.
Actual Python subprocesses verify Unicode JSON exchange, secret-environment removal,
bounded output, error redaction, timeout killing and cancellation reaping.

Nine integration cases (including two parametrized cancellation/deletion cases) use
real 02 routes, durable jobs, worker, migrations and file-backed SQLite with actual
persistent local Chroma from 04. Network inputs and embedding vectors are labelled
test doubles. They verify API import -> transcript -> verified index -> ready,
deduplication, per-item batch failures, no captions, coordinator-owned retry, invalid
transcripts, failed indexes, cancellation/deletion during fetch, persisted vector
reopening, actual vector deletion, higher-generation reimport, profile isolation,
client closure and factory startup-failure cleanup.

HTTP integration uses ASGITransport in process; this change does not claim a new
03-specific deployed HTTP/crash test. Existing 02 regression also includes its own
separate HTTP server/worker process checks. Test databases/indexes are temporary;
existing application databases, indexes and user `.env` files were not used or changed.

## Live observation

The explicit live check read public video `dQw4w9WgXcQ`, using the real caption
subprocess and public oEmbed, without a YouTube API key or Gemini call:

- Selected English manual captions under the configured `th,en` preference.
- Returned **61 segments**, first start **1.36 s**, last end **211.32 s**.
- Available title/author/thumbnail metadata was retrieved.
- Observed attempt latency: **3.703 s**.
- No application database or vector index was written.

This is one successful public-video smoke check, not a guarantee of availability for
other clips, networks or languages. The live Data API metadata path was not tested
without a key. Full live import with paid Gemini indexing was not exercised; the
coordinator/indexing path was validated separately with fixture embeddings.

## Reproduction and retained local evidence

From MiniProject:

```powershell
uv sync --project 03_video_ingestion --locked
uv run --project 03_video_ingestion --locked pytest 03_video_ingestion/tests -q -W error
uv run --project 03_video_ingestion --locked pytest 02_api_backend/tests -q -W error
$env:RUN_LIVE_EMBEDDING_TESTS = "0"
uv run --project 03_video_ingestion --locked pytest 04_rag_knowledge/tests -q -W error
uv run --project 03_video_ingestion --locked ruff check 03_video_ingestion
uv run --project 03_video_ingestion --locked ruff format --check 03_video_ingestion
uv lock --project 03_video_ingestion --check
```

The live read command and local API/worker setup are in [README.md](README.md).
Ignored evidence files:

- `runtime/ingestion-check/ingestion-tests.xml`
- `runtime/ingestion-check/backend-regression.xml`
- `runtime/ingestion-check/rag-regression.xml`
- `runtime/ingestion-check/live-check.json`

No channel/playlist discovery, scheduler, ready-video refresh, authenticated caption
access, speech-to-text, model answer generation or container deployment is included.
Existing root documentation may still describe 03 as planned; this folder records
the actual implementation and its verified limits.
