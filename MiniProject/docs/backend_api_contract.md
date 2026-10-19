# Backend API contract — module 02, version 0.1.0

The implementation lives in `02_api_backend`. Interactive, field-level schemas are
generated at `/docs` and `/openapi.json`. This file records behavior shared with
01 and 03-07. All endpoints use JSON; timestamps are UTC ISO 8601, and publication
filters use inclusive calendar dates. This is a single-user prototype.

## Endpoints

| Method / path | Success | Behavior |
|---|---|---|
| GET /health | 200 | Schema health, mode, configuration; not a live AI check |
| POST /api/videos/import | 202 | Results per input index; no transcript fetch in the request |
| GET /api/jobs/{job_id} | 200 | Durable job state/stage, errors, attempts and final result |
| POST /api/jobs/{job_id}/cancel | 200 | Cancel queued work or request cooperative stop |
| POST /api/jobs/{job_id}/retry | 202 | New bounded attempt group for eligible failed import/delete |
| GET /api/videos | 200 | Paginated non-deleting library |
| GET /api/videos/{video_id}/transcript | 200 | Paginated timestamped segments and provenance |
| DELETE /api/videos/{video_id} | 202 | Hide immediately; queue durable cleanup |
| POST /api/chat | 200 / 202 | Validated final answer, or job ID if still pending/retrying |
| GET /api/conversations/{id} | 200 | Paginated durable turns and citation availability |
| POST /api/analysis | 202 | Durable summary/compare task; poll the job |
| POST /api/research | 202 | Durable task with job_id and run_id (same ID) |
| GET /api/research/{run_id} | 200 | Job/result plus progress events |
| POST /api/research/{run_id}/cancel | 200 | Research cancellation |
| POST /api/learning-artifacts | 202 | Durable artifact task; poll the job |
| GET /api/learning-artifacts/{artifact_id} | 200 | Stored artifact, sources_available and provenance |

Long analysis/artifact requests deliberately use 202 rather than the original
proposed immediate result. This prevents loss on HTTP disconnect or API restart.
Frontend 01 must support polling for these tasks and the occasional 202 chat.
Accepted task responses have a `Location: /api/jobs/{job_id}` header.

## Import and lifecycle

Request: `{"urls":["https://youtu.be/dQw4w9WgXcQ", "invalid"]}`.

```json
{
  "jobs": [
    {"input_index":0,"outcome":"accepted","video_id":"dQw4w9WgXcQ","job_id":"<uuid>","error_code":null},
    {"input_index":1,"outcome":"rejected","video_id":null,"job_id":null,"error_code":"invalid_youtube_url"}
  ],
  "mode":"fixture"
}
```

Supported input is HTTPS `youtube.com/watch?v=...` (including www/m) and `youtu.be/...`.
Only a validated 11-character ID is retained; the adapter receives a canonical
provider URL, never an arbitrary destination. No network request is made to input URLs.
Batch size defaults to 50 (`IMPORT_MAX_URLS`). Invalid items are rejected independently;
202 means the batch was evaluated, and can contain zero accepted items.
Duplicate video IDs return `outcome=existing` and the existing import job, even if
that job failed. A duplicate does not start another import or paid operation.

Video status: `queued -> fetching_transcript -> indexing -> ready`.
Other outcomes: `no_transcript`, `failed`, `deleting`, `deleted`.
Job state is separate: `queued`, `running`, `completed`, `partial`, `failed`, `cancelled`.
Import job `stage` follows the video pipeline. No captions is a completed inspection
with `stage=no_transcript`, `error_code=no_transcript`, `retryable=false`.
No invented progress percentages are returned.

Automatic retry uses bounded exponential backoff, capped at 300 seconds, for retryable
errors only. Maximum attempts defaults to 3. A job has a durable total deadline (180s
by default), and research uses its 120s budget. Queue waiting before the first claim
does not consume the execution deadline. Retry waiting after the first claim does.

Manual retry is allowed only for failed, retryable import/deletion jobs whose video
lifecycle is still current. It creates a new job with a fresh explicit budget; repeated
clicks return the active replacement. Missing captions and permanent restrictions do
not qualify. A new research request/key creates an explicitly new research task.

## Scope and selection

```json
{"video_ids":["dQw4w9WgXcQ"],"channel_ids":[],"playlist_ids":[],"date_from":null,"date_to":null}
```

- `video_ids` is required and nonempty, with at most 100 IDs. Empty does not mean all.
- Every explicit video must exist and be ready before filters apply.
- The video set intersects the selected channels and inclusive publication date range.
  Values within a channel list are ORed. Unknown dates cannot satisfy date filters.
- An empty final set is `empty_scope`; not an authorization to widen selection.
- Nonempty playlist filters are rejected as `unsupported_filter` until implemented.
- The backend freezes the resolved video generations/index versions and rechecks them
  before tools and publication. Deleted/replaced sources invalidate active work.
- Follow-up history includes only completed turns entirely inside the current source
  versions. A conversation ID never authorizes access to other sources.
- Unknown body fields (including client-supplied ownership fields) are rejected.

Library filters: `channel_id`, `date_from`, `date_to`. `playlist_id` is explicitly
rejected. Pagination is `limit` (1-200) and `offset` (>=0). Video/history defaults
to 50 items; transcript defaults to 100. Research event polling uses
`after_event_id` and `limit` and returns ascending IDs.

## Chat, analysis, artifacts, research

Chat input: `{"question":"Explain RAG","conversation_id":null,"scope":{...}}`.
An omitted/null conversation ID creates one. Only one unfinished turn is allowed
per conversation. Pending user turns are saved; successful assistant turns/citations
and the final job result commit together. Failed turns stay visible with job state.

`Idempotency-Key` (1-128 word characters, dot or dash) is recommended for chat,
analysis, research and artifact requests. Same operation/key/input reuses a durable
job/result; different input under the same key returns 409. Without the header, a
new request is a new task. Keys are scoped by operation and, in this prototype,
the single local user. Import deduplication uses the normalized video ID instead.

Final chat response contains `status` (`answered` or `insufficient_evidence`),
`answer`, `citations[]`, `coverage`, `provider_metadata`, `conversation_id`,
`job_id`, `mode`, and `sources_available`. 202 returns `job_id`/`state`; poll the
job to obtain the same final result. Preserve input while pending or on errors.
Historical replay can return `sources_available=false` after deletion.

Analysis input: `{"type":"summary|compare","scope":{...},"instruction":""}`.
Comparison requires at least two resolved ready videos. Result follows the answer
schema and coverage contract.

Artifact input: `{"type":"quiz|flashcards|study_plan","scope":{...},"topic":"",
"level":"beginner","days":7}`. `days` is 1-90 and applies to study plans.
Job results include `artifact_ids`; retrieve each saved artifact by ID.
Artifact content is type-checked:

- Study plan: `days[]` with consecutive `day`, `topic`, `citations[]`.
- Quiz: `questions[]` with `question`, `answer`, `explanation`, `citations[]`.
- Flashcards: `cards[]` with `front`, `back`, `citations[]`.

Every item must reference a known citation in that artifact. Full study plans must
contain the requested number of days.

Research input: `{"goal":"Learn RAG","scope":{...},"level":"beginner","days":7}`.
Events store step, tool_name, state, summary and timestamp (no hidden reasoning).
Completed/partial results contain content, artifacts, citations, coverage and provider
metadata. Research is not automatically replayed after a crash: without checkpoints,
replaying would hide repeated work and reset step budgets. Events are retained on failure.
Module 06 must return honest partial findings before its hard deadline; hard timeout
without a valid final result is `failed`, not fabricated partial content.

## Evidence, coverage and model metadata

Citation fields: `citation_id`, `chunk_id`, `video_id`, `title`, `start_seconds`,
`end_seconds`, `url`. 05/06 return IDs matching scoped 04 evidence. 02 verifies
source/version/interval identity and overall stored transcript bounds; it rebuilds
the URL from video ID and floored start seconds, and takes title from evidence.
This structural verification does not prove semantic support for every claim; 05/07
must evaluate that. Answered outputs and completed learning outputs need citations.

Coverage fields: `expected_videos`, `processed_videos`, `expected_chunks`,
`processed_chunks`, `complete`, `notes[]`. Unknown chunk counts use null together.
Complete requires equal known counts; expected counts are checked against 04 inventory.
Incomplete full-analysis results need explanatory notes. Actual processing counts
are supplied by 05/06; 02 does not claim to independently observe model reading.

`provider_metadata` contains provider, requested_model, returned_model (nullable),
usage and measured latency_ms. In fixtures, provider is `fixture`, no actual model
is reported, usage is empty and latency is zero for the synthetic generation step.
The requested configurable model remains `gemini-3.5-flash`.

## Deletion, cancellation and retention

DELETE hides the video immediately, cancels dependent queued work, requests running
work to stop and queues cleanup. Active import/delete operations serialize per video.
Running operations must yield and honor cancellation. Recovery fences stale claims;
external 04 adapters must enforce generation/version fencing too. New imports are
rejected while deleting. Once deleted, an explicit reimport gets a higher generation.

Vector/transcript cleanup is idempotent and durable. Failed deletion leaves the video
hidden until repaired/retried. Deletion cannot be cancelled halfway through.
Messages, saved results/artifacts, job audits and a minimal lifecycle tombstone remain;
this preserves history while marking its sources unavailable. It does not erase all
past conversation text. `source_available` is reported for history citations, and
`sources_available` for task/artifact results. No account-wide erasure API exists yet.

## Errors and delivery

```json
{"error":{"code":"video_not_ready","message":"Every selected video must be ready","retryable":false,"request_id":"<uuid>"}}
```

Chat processing errors also include `job_id` so the client can inspect durable state.
Error statuses: 400 invalid individual URL (batch responses report per-item codes);
404 unknown resources; 409 lifecycle/scope/idempotency conflicts; 422 invalid body,
unsupported filters or limits; 502 invalid dependency output/unexpected dependency
failure; 503 unavailable dependency; 504 deadline. Retryable chat failures normally
return 202 while the durable coordinator still has retries remaining.

Every response has `X-Request-ID` and `X-Adapter-Mode`; request IDs are carried into
jobs/logs. No raw model exception, credentials or request bodies are returned/logged.
Streaming is disabled; there are no provisional unvalidated answer events.
Jobs persist their adapter mode. Reusing a fixture database with a different adapter
mode is rejected; select a new database instead of relabelling synthetic knowledge.
