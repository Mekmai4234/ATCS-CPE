# Module 04 — Gemini migration verification

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
