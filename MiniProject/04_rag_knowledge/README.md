# Module 04 — Gemini RAG Knowledge

Timestamp-preserving chunks, Gemini embeddings, persistent local Chroma, authorized
retrieval, complete chunk enumeration, replacement and deletion. Gemini is the only
live AI provider in 04; a deterministic fixture adapter supports offline tests.
02 owns jobs/transcripts/ready states; 05/06 own answer generation and research.
Source changes are confined to this folder. See [TEST_REPORT.md](TEST_REPORT.md).

The account-aware release requires 02's ownership/session contract (PR #18).
See [AUTHORIZATION.md](AUTHORIZATION.md) for the trusted execution boundary,
account-bound signed cursors, shared-source GC and the additive stopped upgrade.
No embedding/vector metadata migration or bulk re-embedding is needed. Do not
deploy this as a standalone Google login implementation.
The consumer lock targets backend `b047e809` or compatible account-aware metadata;
before #18 merges, use the locked-candidate procedure in AUTHORIZATION.md instead
of installing against old develop. Latest evidence is in
[LOCK_HANDOFF_TEST_REPORT.md](LOCK_HANDOFF_TEST_REPORT.md).

## Install and test

From `MiniProject`, with Python 3.11–3.13 and uv:

```powershell
uv sync --project 04_rag_knowledge --locked
uv run --project 04_rag_knowledge --locked pytest 04_rag_knowledge/tests -q
uv run --project 04_rag_knowledge --locked ruff check 04_rag_knowledge/src 04_rag_knowledge/tests 04_rag_knowledge/scripts
uv run --project 04_rag_knowledge --locked ruff format --check 04_rag_knowledge/src 04_rag_knowledge/tests 04_rag_knowledge/scripts
```

The lockfile includes `../02_api_backend`, the owner of shared schemas/execution
contracts. Normal tests require no key: REAL Chroma, temporary SQLite and fixture
vectors are used. Gemini HTTP tests use MockTransport. Live tests are skipped unless
`RUN_LIVE_EMBEDDING_TESTS=1` is explicitly set. No tokenizer/model download is needed.

## Configure Gemini

Copy `04_rag_knowledge/.env.example` to `04_rag_knowledge/.env` ONLY if no local file
exists, and enter a server-side `GEMINI_API_KEY` locally. Never put keys in source,
commits, reports or Docker build arguments. The key supplied for validation is not
saved in the delivered configuration; use your replacement key for subsequent runs.

Precedence: process environment > 04's local `.env` > shared `MiniProject/.env` >
defaults. The 04 override file avoids editing other modules. Shared templates may
still describe the old embedding proposal; the team should align them separately.
Runtime storage paths resolve from `MiniProject`, regardless of the working directory.

| Setting | Default |
|---|---|
| `EMBEDDING_PROVIDER` | `gemini` (or explicit offline `fixture`) |
| `EMBEDDING_MODEL` | `gemini-embedding-2` |
| `GEMINI_API_KEY` | empty; required for real Gemini calls |
| `EMBEDDING_DIMENSIONS` | `1536`; supported 128–3072 |
| `EMBEDDING_TOKENIZER` | `utf8-byte-budget-v1` |
| `CHROMA_PERSIST_DIR` | `./runtime/chroma` |
| `CHUNK_TARGET_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `600` / `100`; see counting note below |
| `RETRIEVAL_TOP_K` | `8`, range 1–100 |
| `EMBEDDING_BATCH_SIZE` | `16`, range 1–64 |
| `RAG_OPERATION_TIMEOUT_SECONDS` | `60`, bounded by remaining job time |

The OpenAI adapter/dependency and tiktoken are removed. `OPENAI_API_KEY` is not used by
04. `LLM_MODEL` remains 05/06's generation model and does not select an embedding model.
Gemini Developer API is selected explicitly; there is no fallback to another provider.

### Counting and retrieval formats

The existing `CHUNK_*_TOKENS` setting names are retained for integration compatibility,
but now mean conservative **UTF-8 byte budgets**, not billable Gemini token counts.
`Chunk.token_count` uses that budget and is labelled by
`token_count_kind=utf8-byte-budget-v1`. Chunk schema is version 2. This offline method
is deliberately conservative, especially for Thai; chunk-size tuning remains evaluation
work. It does not claim an OpenAI tokenizer matches Gemini or estimate invoice usage.

Before EVERY live embedding, Gemini `countTokens` counts each final formatted input
and enforces the model's 8192-token ceiling. Prepared input also has an 8000-byte local
cap. Counting and embedding share one deadline; there is no silent truncation or bypass
when counting fails. The extra count requests increase latency and consume applicable
quota. `counted_input_tokens` in evaluation reports is preflight measurement, not a bill.

Documents use `title: {title} | text: {text}`; questions use
`task: search result | query: {question}`. Original evidence text/titles/timestamps are
kept separately. Titles used in the embedding prefix are bounded. Gemini Embedding 2
does not receive the older `task_type` parameter. Each chunk becomes its own `Content`
object, avoiding aggregation of several chunks into one vector. Output count, dimension
and finite/nonzero values are validated. HTTPX async transport is explicit; SDK retries
are disabled so 02 owns bounded retries. Raw provider exceptions/credentials are redacted.

## Initialize and connect

From `MiniProject`, initialize the existing backend schema, then the additive 04 tables:

```powershell
uv run --project 04_rag_knowledge --locked yk-db upgrade head
uv run --project 04_rag_knowledge --locked yk-rag init
```

Both use the configured `DATABASE_URL`. `rag04_schema`, `rag04_runs`, `rag04_active` and
`rag04_chunks` live in the SAME SQLite DB as backend leases/lifecycle. No backend source,
tables or Alembic migrations were changed. Unknown 04 DB schema versions are rejected.

`youtube_rag.integration.RagAdapters` supplies:

- `index(source, transcript, context) -> IndexReceipt`
- `delete(video_id, generation, context) -> None`
- `evidence(sources, chunk_ids, context) -> list[Evidence]` (exact citation lookup)
- `inventory(sources, context) -> int` (actual published Chroma vector counts)

The team factory constructs it with 02's settings/repository and delegates those methods.
The supplied `create_adapters` is a 04-only factory: ingest/answer/analyze/research/artifact
still report `dependency_unavailable`. Implementing 04 does not connect live 03/05/06.
At shutdown, its owner should call `await knowledge.close()`.

For 05/06, reuse the same service and the current authorized backend context:

```python
from youtube_rag.manifest import BackendExecution

execution = BackendExecution(context)
hits = await knowledge.rag.search(question, sources, execution, top_k=8)
cursor = None
while True:
    page = await knowledge.rag.read_video_chunks(sources, execution, limit=100, cursor=cursor)
    # Process page.items and track the chunks actually processed.
    cursor = page.next_cursor
    if cursor is None:
        break
```

Sources must be a nonempty subset of the current job's frozen video/generation/transcript
versions. 02 intersects channel/date filters; 04 filters EXACT published run IDs before
ranking and rechecks identities after async work. Empty scope never means all. Unsupported
playlists remain rejected by 02. Existing single-user behavior is preserved; future
ownership requires changes at both application and vector boundaries.

Search returns `SearchHit(chunk, ranking_score)` using cosine ranking (1-distance), not
confidence probability. Optional `min_score` is a caller-selected cutoff, not a calibrated
relevance guarantee. 05 decides evidence sufficiency. Exact lookup returns 02's strict
Evidence schema without extra score/URL fields; 02 constructs timestamp URLs. Pages
return snapshot-bound cursors, available counts and missing sources. Delivering chunks
does not prove 05/06 processed them; top-k cannot establish full-video coverage.

## Replacement and migration

Public chunk IDs are deterministic; every attempt stages vectors under a unique run ID.
Only active manifest runs are searchable. All expected IDs must exist before publication.
A short SQLite transaction checks 02's `_owned` lease guard, cancellation, deadline and
video generation/version/status, then changes the manifest pointer atomically. This
isolated v0.1 private-interface dependency is integration-tested. Chroma is not part of
a distributed transaction: crashes may leave invisible staging vectors for offline GC.

Changing from the old OpenAI index requires explicit reindex; matching vector dimensions
alone does not make providers compatible. Provider/model, formatting, dimensions, counting,
chunk layout and chunk schema participate in the new fingerprint. Old configurations fail
clearly rather than mixing vectors. The existing rag04 DB table schema remains version 1;
the version-2 chunk JSON needs no destructive table migration. The October 19 update
adds `rag04_store_binding` through `yk-rag init`, without altering backend tables.

### Runtime configuration and store pairing

`yk-rag config` prints resolved SQLite/Chroma locations, provider/model/dimensions,
collection and index fingerprint, never credentials. Maintenance defaults to `--profile auto`,
which selects the RAG configuration used by the configured `ADAPTER_FACTORY`:

| Profile | RAG configuration source |
|---|---|
| `module04` | Root `.env`, then `04_rag_knowledge/.env` |
| `ingestion03` | Root, 04, then `03_video_ingestion/.env` |
| `team05` | Root, 04, 03, 06, then `05_ai_answers_analysis/.env` (same order as 05) |
| `backend` | Resolved backend settings, including 02's offline fixture overrides |

The SQLite configuration follows backend `Settings`: root `.env`, then
`02_api_backend/integration/.env`. Process environment takes precedence over env files.
Use an explicit profile for a custom factory that uses one of these conventions.
For another deployment, repeat `--env-file PATH` in precedence order; this replaces
default file lists for both settings objects. Every explicit file must exist. In the
backend profile, the runtime's offline overrides still apply. These options belong
after the subcommand. No module 02/03/05 configuration files are edited by this CLI.

Each database is paired with the Chroma directory through a random identity stored in
`rag04_store_binding` and `.yk04-store.json` inside that directory. A new empty index is
paired on first indexing. A populated foreign Chroma cannot be paired automatically.
Wrong/missing/corrupt markers fail before staging, publication, deletion or GC changes
the manifest. Read/delete requests do not create missing Chroma collections. Maintenance
also refuses a nonexistent SQLite path without creating a database there.

**Existing indexes need a one-time stopped upgrade.** Back up the pair first, inspect
`yk-rag config`, run `yk-rag init`, then `yk-rag bind-store --workers-stopped` using the
same profile/env files. Binding verifies exact persisted IDs for every published/retired
run against SQLite before recording an identity; it neither embeds nor reindexes data.
Missing/incomplete legacy vectors or a legacy store with no complete run are refused.
Use a known complete paired backup to recover these cases. Do not delete/rewrite markers
to bypass a mismatch. Pair creation is not a distributed transaction: an interruption
between marker creation and SQLite commit fails closed. Explicit legacy binding can
recover a complete verified index; an interrupted empty initialization requires its
pre-upgrade backup or a fresh isolated state directory.

Finish/cancel queued/running jobs, stop API AND workers, back up SQLite plus Chroma, set
the Gemini configuration, then run from `MiniProject`:

```powershell
uv run --project 04_rag_knowledge --locked yk-rag config
uv run --project 04_rag_knowledge --locked yk-rag init
uv run --project 04_rag_knowledge --locked yk-rag bind-store --workers-stopped
uv run --project 04_rag_knowledge --locked yk-rag reindex --video-id dQw4w9WgXcQ --workers-stopped
uv run --project 04_rag_knowledge --locked yk-rag gc --workers-stopped
```

For example, add `--profile team05` to **each** command when explicitly targeting the
05 team factory, or add `--env-file .env --env-file 04_rag_knowledge/.env` to each command
when those two existing files are the complete deployment configuration. Compare the
`config` output with the running API/worker before stopping them for maintenance.

Reindex every selected ready video. Replacement publishes only after success; failures
keep the previous index. Superseded runs are cleaned afterward. Deletion hides manifests
before deleting generations <= the authorized bound, and cleanup is retryable. A title-only
update also replaces the run, because the title participates in Gemini's embedding input
even though 02's transcript hash excludes metadata. GC removes
retired/deleting/abandoned staging records; never run staging GC with writers active.
GC needs no Gemini key and makes no embedding calls. Metadata is removed only after
deletion and an empty-vector verification succeed; failures retain retryable cleanup state.
The maintenance flag asserts processes are stopped; it is not a process manager.

Chroma uses a private killable subprocess so blocking calls cannot stop async heartbeats
or keep mutating in an abandoned thread after cancellation. Chunking yields/checks between
pieces/chunks, preserves Unicode and keeps the original segment interval when splitting
oversized captions. Transcript text, including instruction-like text, is evidence only.
Back up/restore SQLite and the **whole Chroma directory including `.yk04-store.json`**
together while stopped. Close database/vector clients or use a consistent SQLite backup;
do not copy a live SQLite file without its WAL state. The pair can move to a new path
without changing its identity. Verify compatible configs, inventory and citations after
restore. A matching marker identifies the pair, not its backup age: both snapshots must
come from the same stopped backup. Production load and hybrid search remain future work.

## Evaluation and Docker

From `MiniProject`:

```powershell
uv run --project 04_rag_knowledge --locked yk-rag evaluate --state 04_rag_knowledge/runtime/reference
uv run --project 04_rag_knowledge --locked yk-rag evaluate --state 04_rag_knowledge/runtime/reference --phase verify
```

Fixtures contain two labelled synthetic Thai/English transcripts and eight reference
questions, including paraphrases. Offline hash embeddings verify mechanisms, not semantic
quality. Use a NEW state directory for each dataset/configuration. With a configured
Gemini key, `yk-rag evaluate --live --state 04_rag_knowledge/runtime/live` explicitly calls
Gemini. Scope, ranks, inventory and restart comparisons are reported; the small corpus
cannot establish production accuracy.

From `MiniProject/04_rag_knowledge`, for offline Docker checks:

```powershell
docker compose -f compose.test.yaml -p yk04-gemini build tests persistence
docker compose -f compose.test.yaml -p yk04-gemini run --rm --no-deps tests
docker compose -f compose.test.yaml -p yk04-gemini run --rm --no-deps tests ruff check src tests scripts
docker compose -f compose.test.yaml -p yk04-gemini run --rm --no-deps tests ruff format --check src tests scripts
docker compose -f compose.test.yaml -p yk04-gemini run --rm --no-deps persistence yk-rag evaluate --state /data --phase seed
docker compose -f compose.test.yaml -p yk04-gemini run --rm --no-deps persistence
```

Containers are non-root, have networking disabled and empty Gemini keys. Seed/verify run
in separate containers sharing a volume. The Dockerfile allowlist excludes all local
credentials/runtime data. Root Compose files are unchanged. `down` retains reference data;
add `--volumes` only when deliberately removing this isolated check project's data.

`scripts/live_check.py` explicitly runs the live test, real Gemini+Chroma reference indexing,
retrieval, then reopen/verify. It accepts `GEMINI_API_KEY`, `--key-file` for a temporary
ignored file, or `--stdin-key`. Keys are never passed on argv or written into the report.
For a live container check, pass the key via stdin to `docker run --rm -i --init
--network bridge --entrypoint python yk04-gemini-tests scripts/live_check.py --stdin-key`.
This is separate from the network-disabled suite; do not bake keys into images.

References: [Gemini embeddings](https://ai.google.dev/gemini-api/docs/embeddings),
[Google GenAI SDK](https://googleapis.github.io/python-genai/),
[Chroma configuration](https://docs.trychroma.com/docs/collections/configure).
