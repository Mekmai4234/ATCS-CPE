# Module 03 — Subprocess cleanup and acceptance follow-up

Verified on **2026-10-20 (Asia/Bangkok)** against the local
`feature/03_video_ingestion` checkout based on `f7b8a41`. The supplied audit document
references `develop@25427fe`; these results describe this local checkout, without
merging or claiming verification of that newer branch. All source/documentation
changes are confined to module 03. Verification was completed before publication.
No deployment was performed.

## Reproduced failure and correction

Reproduced the supplied audit's real-child case: a 20 MiB stdout producer, the unchanged
production response limit of 8 MiB, and a fetch timeout of 0.5 seconds. Before the fix,
the fetch was still pending after 3 seconds. Manually draining stdout released it with
`invalid_transcript` after 3.015 seconds. The issue is real: asyncio process waiters can
remain blocked by a paused/full stdout pipe even after the child is killed.

`captions.py` now:

- Kills the child first, then drains buffered stdout and joins the process with
  `communicate()`, and waits for stdin closure.
- Gives drainage a separate **2-second** budget. If it stalls, closes the asyncio
  process transport and gives the final reap another **0.5 seconds**. This private
  transport access is isolated to the fallback because asyncio.Process has no public
  `close()` method.
- Shields the bounded cleanup task from repeated caller cancellation, then preserves
  cancellation for the caller. Tracks and removes completed fetch/cleanup tasks.
- Cancels and joins active fetch owners during shutdown, avoiding concurrent reads
  from one stdout StreamReader, and ensures metadata client closure through the
  existing service lifecycle.
- Fails with the classified non-retryable `ingest_cleanup_timeout` and disables new
  fetches if the final reap itself cannot complete. It does not wait indefinitely.

The configured fetch timeout excludes final cleanup: worst-case cleanup allowance is
an additional **2.5 seconds**, rather than a claim of a strict total 0.5-second wall time.
In the exact 20 MiB reproduction after the fix, the result was `invalid_transcript`
in **0.125 seconds**, the child was reaped, and fetch/cleanup task counts were both zero.
This is an observed runtime, not a guaranteed service latency.

## Verification results

| Check | Observed result |
|---|---|
| Final module 03 suite, warnings as errors | **78 passed**, 32.52 s |
| Module 02 regression, warnings as errors | **68 passed**, 22.17 s |
| Module 04 regression, warnings as errors; live Gemini opt-in disabled | **77 passed, 1 skipped**, 90.40 s |
| Ruff lint / formatting | Passed |

New regressions use actual child processes, not just subprocess mocks. They cover:

- A real 20 MiB output, without lowering the 8 MiB production ceiling.
- Timeout and cancellation while the actual stdout reader is paused with buffered data.
- A second cancellation during cleanup.
- Forced stalled drainage exercising transport-close/final-reap fallback.
- Forced stalled final wait proving its independent hard budget and classified failure.
- Service shutdown with two active children and full stdout pipes; children, task sets
  and metadata client are closed.
- The new acceptance script with real SQLite/Chroma and offline HTTP/caption doubles,
  including refusal to touch an existing nonempty state directory.

Failure watchdogs release pipes before failing a regression, so a recurrence does not
leave pytest itself blocked on the original cleanup bug. Existing no-captions, retry,
metadata, credentials, index-failure and durable cancellation tests also passed.
The intentionally skipped 04 case is its opt-in paid/live Gemini check.

## Real public YouTube checks

These ran real caption subprocesses and public oEmbed, without YouTube/Gemini keys.
Expected provider failures make `live_check.py` return a nonzero exit code; they are
recorded as observed classifications, not claimed as successful caption retrieval.

| Case | Actual observation | Elapsed |
|---|---|---|
| Thai-only `wD3NSzYtsMc` | Thai manual captions, **281 segments**, metadata available; 0.0–934.64 s | 3.032 s |
| English-only `dQw4w9WgXcQ` | English manual captions, **61 segments**, metadata available; 1.36–211.32 s | 2.890 s |
| `jNQXAC9IVRw`, default languages | English manual captions, **6 segments**, metadata available | 2.609 s |
| `dQw4w9WgXcQ`, Thai-only preference | `no_transcript`, non-retryable | 2.500 s |
| `00000000000` | `video_unavailable`, non-retryable; separate metadata warning | 2.266 s |
| Additional candidate `QH2-TGUlwu4` | `video_unavailable`, non-retryable in this environment | 2.500 s |

The no-transcript case means **no usable captions in the requested language**; the
English track exists. A video lacking every possible caption language was not independently
established. Provider timeout remains deterministic injected transport/child testing,
not a claim that a public provider happened to time out. No API credentials or upstream
exception messages were written to reports. The keyed Data API path has mock coverage;
no live Data API key was used.

## Live captions through 02 and 04

Added `scripts/acceptance_check.py` to make the combined check reproducible. It requires
an explicit `--fixture-embeddings` flag and a **new empty directory**; it refuses to
migrate existing application data. The temporary persistent database has an acceptance-only
adapter identity and cannot be reopened by the production live factory.

| Video | Stored language/segments | Actual Chroma chunks | Provider timestamps | Duplicate URL | Elapsed |
|---|---|---|---|---|---|
| `wD3NSzYtsMc` | th / 281 | 58 | All match exactly | Same job; one caption fetch | 5.343 s |
| `dQw4w9WgXcQ` | en / 61 | 5 | All match exactly | Same job; one caption fetch | 3.250 s |

Both cases passed actual API import -> durable job -> real caption fetch -> transcript
persistence -> 04 indexing/inventory verification -> **ready**. All stored segments were
paginated and compared to their original provider start/duration values. The complete
check took **9.250 seconds** including initialization. HTTP uses in-process ASGITransport;
SQLite, worker execution, transcript data and persistent Chroma are real.

**Embedding values are fixture hashes.** No Gemini embeddings or model generation were
called, and no semantic retrieval/answer-quality claim is made. This isolates the 03/02/04
mechanics from the separate provider/configuration work in 04. No existing application
DB/index or user `.env` was changed. No Docker/deployment verification was performed.

## Reproduce and inspect

See [README.md](README.md) for normal test commands and the new isolated acceptance command.
Use a fresh state directory on each run. The retained local evidence is ignored by Git:

- `runtime/ingestion-followup/ingestion-tests.xml`
- `runtime/ingestion-followup/backend-regression.xml`
- `runtime/ingestion-followup/rag-regression.xml`
- `runtime/ingestion-followup/cleanup-reproduction.json`
- `runtime/ingestion-followup/thai-live.json`
- `runtime/ingestion-followup/english-live.json`
- `runtime/ingestion-followup/short-video-live.json`
- `runtime/ingestion-followup/no-preferred-captions-live.json`
- `runtime/ingestion-followup/unavailable-live.json`
- `runtime/ingestion-followup/no-captions-live.json` (the extra unavailable candidate)
- `runtime/ingestion-followup/acceptance-20261020/report.json`, `app.db`, `chroma/`

The original [TEST_REPORT.md](TEST_REPORT.md) is retained as the dated initial-implementation
record. Documentation now describes the cleanup budget and distinguishes live captions,
fixture embeddings, injected failures and unverified provider/deployment work.
