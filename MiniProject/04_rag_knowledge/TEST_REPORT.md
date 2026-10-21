# Module 04 — Maintenance/store-pair verification

For the 2026-10-21 account-aware changes, see
[AUTHORIZATION_TEST_REPORT.md](AUTHORIZATION_TEST_REPORT.md). The results below
describe the earlier maintenance update and migration checks.

Verified on 2026-10-19 against the current integrated checkout (`25427fe`). Changes
are limited to module 04. No commit, push, PR, deployment or migration of existing
application data was performed in this update.

## Current executed results

| Check | Observed result |
|---|---|
| Windows module 04, warnings treated as errors | **97 passed, 1 skipped**, 106.37 seconds |
| Docker Linux module 04, warnings treated as errors | **97 passed, 1 skipped**, 116.57 seconds |
| Existing 02 regression, warnings treated as errors | **68 passed**, 18.64 seconds |
| Existing 03 regression, warnings treated as errors | **69 passed**, 18.81 seconds |
| Ruff lint/format on host and Docker | Passed, 23 Python files |
| `uv lock --check`, `git diff --check` | Passed; no dependency/lock changes |
| Change-scope / credential-pattern audit | 11 changed/new files, all in 04; no matching credential patterns |
| Docker seed -> separate verify container, shared isolated volume | Passed; 2 videos, 7 chunks, 8/8 fixture questions within top 3; scope preserved |
| Live captions through unchanged 03 | One successful English manual transcript, 61 segments |
| Real-caption 04 lifecycle smoke, host and Docker | Passed; 16 chunks, reindex/reopen, inventory/evidence/timestamp identity, scoped Thai/English queries and deletion |

The 20 new regression cases cover runtime/maintenance env divergence, explicit file
precedence, automatic 02/03/05 factory profiles, secret-free configuration output,
wrong/missing/corrupt pair markers, incorrect SQLite paths, foreign populated stores,
verified legacy adoption, retry after initial embedding failure, cleanup failures and
post-delete verification, provider-free GC, stopped backup relocation/mismatched restore,
and reindex/restart/bilingual scope/evidence/delete behavior. Existing tests continue
covering lease/cancellation/lifecycle fencing, pagination and embedding migration.

Wrong-store reindex/GC/delete leave the manifest unchanged and do not create the wrong
directory. Legacy adoption rejects an absent or empty wrong store without changing the
manifest. Failed/no-op vector deletion retains cleanup metadata for retry. Existing v1
schema upgrades add only the 04-owned binding table and preserve chunks and active runs.

## Current limitations and isolation

- The Gemini live test was skipped because no key was configured for this run. No paid
  Gemini request was made. Historical live checks below were not repeated in this update.
- Real captions were read from public video `dQw4w9WgXcQ` using the unchanged 03 adapter,
  then processed through real SQLite/Chroma with **fixture embeddings**. Thai/English
  queries verify scope and evidence mechanics, not cross-language semantic relevance.
  Native Thai live-caption retrieval and current live Gemini quality remain unverified.
- A prior read of `aircAruvnKk` was rejected by 03 as `invalid_transcript`. No 03 code was
  changed, and that transcript was not indexed. Both read results are retained locally.
- Existing user `.env` files, application databases and indexes were not changed. All new
  state is temporary or inside module 04's ignored `runtime/`. Read-only 02/03 source was
  used for configuration compatibility; their suites were run without source changes.
- Docker checks used non-root containers with networking disabled and no Gemini key.
  The real-caption corpus/probe was mounted separately from ignored runtime data; it is
  not baked into an image. The YouTube read itself ran on the host.
- Existing stores require a stopped `init` then verified `bind-store` upgrade. The pair
  marker is part of the backup. This was exercised on isolated copies, not deployed data.
  Marker/SQLite creation is not a distributed transaction; interrupted pairing fails
  closed as documented in README. `--workers-stopped` remains an operator assertion.

## Reproduction and retained evidence

From `MiniProject/04_rag_knowledge`:

```powershell
uv run --locked pytest tests -q -W error --junitxml=runtime/maintenance-local-tests.xml
docker compose -f compose.test.yaml -p yk04-maintenance build tests persistence
docker compose -f compose.test.yaml -p yk04-maintenance run --rm --no-deps tests pytest tests -q -W error -o cache_dir=/tmp/pytest-cache
docker compose -f compose.test.yaml -p yk04-maintenance run --rm --no-deps persistence yk-rag evaluate --state /data --phase seed
docker compose -f compose.test.yaml -p yk04-maintenance run --rm --no-deps persistence
```

Retained ignored evidence: `runtime/maintenance-local-tests.xml`,
`runtime/maintenance-docker-tests.log`, `runtime/maintenance-backend-tests.xml`,
`runtime/maintenance-ingestion-tests.xml`, `runtime/maintenance-docker-seed.log`,
`runtime/maintenance-docker-restart.log`, `runtime/maintenance-audit.json`, and
`runtime/real-captions/` ingestion and
host/container lifecycle result JSON files. The isolated Docker volume is
`yk04-maintenance_reference-data`. Real-caption probe scripts and their corpus remain
local under `runtime/`; they are excluded from version control and the build context.

## Earlier Gemini migration verification (historical)

The following results describe the earlier migration, not the current October 19 run.

Gemini is the only live embedding provider in this working tree. OpenAI SDK/adapter
and tiktoken were removed. All repository changes are in `04_rag_knowledge`.
Validation used isolated fixtures and temporary stores; existing application data was not used.

## Executed results

| Check | Result |
|---|---|
| Windows offline suite, final source | **77 passed, 1 skipped**, 64.97 seconds |
| Docker Linux offline suite, final image | **77 passed, 1 skipped**, 66.34 seconds |
| Existing 02 suite in the Gemini 04 environment | **56 passed**, 13.81 seconds |
| Live Gemini SDK test, Windows | **1 passed**, warnings treated as errors |
| Live Gemini SDK test, Docker | **1 passed**, warnings treated as errors |
| Real Gemini + Chroma reference evaluation, Windows and Docker | **8/8 supporting segments found within top 3**, authorized scope preserved |
| Reopen real Gemini reference indexes in new service processes | Passed, IDs/ranks identical |
| Offline Docker seed -> separate verify container with persistent volume | Passed |
| Offline CLI seed -> separate verify process | Passed |
| Ruff lint / format, Windows and Docker | Passed, 20 Python files |
| Temporary-key audit | 41 version-control candidates/runtime artifacts checked; no key matches; temporary file removed |

The standard offline suite intentionally skips its live test, even when real integration
is available. Live tests were executed SEPARATELY with the supplied key, on both platforms;
the skip does not mean the live adapter is untested. No live YouTube or 05/06 generation
was invoked. Fixtures are synthetic and labelled.

## Environment and isolation

- Windows Python 3.11.16; Docker Linux Python 3.11.17; uv 0.12.9.
- Docker Engine 29.8.0, Linux containers, non-root UID 10001.
- Locked Google GenAI SDK 2.31.0, HTTPX 0.28.1, ChromaDB 1.5.9.
- pytest 9.1.1, pytest-asyncio 1.4.0, Ruff 0.17.1.
- Offline containers: network disabled, empty Gemini key, no live-test opt-in.
- Live container: explicit bridge networking; key supplied over stdin, not argv,
  Docker build args, image layers or Docker environment configuration.
- SQLite uses actual 02 migrations/repository/jobs; Chroma is REAL persistent local storage.
- Test/evaluation databases are temporary or isolated under this module's ignored runtime/.
- The provided key was used only during verification. No key is delivered in `.env`.
  `.env.example` contains an empty key field and documents local setup.

## Migration and adapter checks

- Provider defaults to gemini / gemini-embedding-2 / 1536 dimensions.
- Invalid/old provider configurations, generation-model IDs and invalid dimensions fail.
- Module-local configuration can override the old shared proposal without editing other files.
- UTF-8 chunk budgets are explicitly labelled; they are not passed off as Gemini token counts.
- Real countTokens preflight covers each final document/query string, enforces 8192 tokens
  and shares the embedding deadline. Empty/invalid/oversized count responses prevent embedding.
- Documents use title/text formatting; queries use the retrieval query prefix.
- Separate Content objects produce separate vectors, with exact output count/shape checks.
- Gemini output normalization at 1536 dimensions was checked live; distinct document vectors
  and query vectors were returned successfully.
- Mocked HTTP verifies requests, dimensions and no legacy task_type field, including token
  preflight before the SDK batchEmbedContents endpoint.
- 400/401/403/429/500/503, transport errors, deadline and cancellation behavior are checked.
- SDK retries are disabled. 02 owns retries; raw provider messages/credentials are not returned.
- Explicit HTTPX transport avoids optional aiohttp behavior; the adapter closes its owned client.
- Invalid/aggregated vector responses, zero/nonfinite values and bad batches are rejected.

## Knowledge layer regression checks

- Stable chunk IDs, complete segment references, real source intervals and bounded overlap.
- Unicode-safe oversized Thai captions and cooperative chunking cancellation.
- Index retry idempotency, incomplete embedding invisibility, actual vector inventory checks.
- Backend ready status requires matching receipt/inventory; heartbeat stays live during Chroma startup.
- Atomic publication rejects expired leases/deadlines, cancellation, deletion and stale workers.
- Authorized source/version filters, channel/date intersection and unsupported playlists.
- Transcript replacement, explicit configuration migration and preservation of a good old index
  after failed reindex. Title-only changes replace the run because titles now affect embeddings.
- Generation-aware idempotent deletion, higher-generation reimport and stale-delete rejection.
- Exact citation evidence bounds, full enumeration, missing-index counts and snapshot cursors.
- Chroma cancellation kills/reaps its subprocess; persisted indexes reopen successfully.
- Schema initialization is repeatable and rejects unknown rag04 table versions.

## Live retrieval smoke dataset

`fixtures/evaluation.json` has two synthetic Thai/English transcripts and eight questions,
including two paraphrases. The evaluated Gemini index contained **7 chunks**. Both host
and container runs found every expected supporting segment within top 3 and preserved scope.
Seven questions had the expected supporting segment at rank 1; one English question had
it at rank 2. New service processes reopened the index and returned the same IDs and ranks.

The seed phase counted 308 prepared input tokens across 15 count requests and made 10
embedding requests (including the eight query embeddings). Verify counted 110 query input
tokens and made eight embedding requests. These counters exclude the separate live SDK
test/probe and are preflight measurements, not an invoice or application latency benchmark.

This is a small smoke dataset. It does not establish real-video accuracy, robust Thai
retrieval quality, unsupported-answer abstention or production throughput. 05 still decides
evidence sufficiency and records actual summary processing; returned chunks are not proof
that an answer model read them.

## Reproduction and local artifacts

Commands and migration steps are in [README.md](README.md). Reports under ignored `runtime/`:

- `gemini-local-tests.xml`, `gemini-backend-regression.xml`
- `gemini-live-local.json`, `gemini-live-docker.json`
- `gemini-docker-build.log`, `gemini-docker-tests.log`
- `gemini-docker-seed.log`, `gemini-docker-restart.log`
- `gemini-offline-evaluation.json`, `gemini-offline-restart.json`
- `gemini-key-audit.json`

`yk04-gemini_reference-data` is an isolated Docker reference volume retained for repeat checks.
Disposable check containers are removed. The root Compose configuration and other modules'
source/configuration were not edited.

Publication still intentionally uses 02 v0.1's transaction-level `_owned` guard. SQLite
publication and Chroma are not a distributed transaction; interrupted staging is invisible
and explicit offline GC handles leftovers. Production deployment, ownership and backup/restore
drills remain separate work. No existing user index was deleted or migrated automatically.
