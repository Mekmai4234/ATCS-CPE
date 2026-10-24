# Module 04 media text retrieval and Free Tier handoff

Date: 2026-10-24. Base: develop `1814bf3622eb62f0963da4f682ea31661728907c`.
Dependency: 02 PR #27 at `b3bb18d` (exact full revision recorded by the candidate
checker). Only module 04 is changed. This is an implementation of the 04 consumer,
not a claim that visual chat, UI, extraction or the entire system is integrated.

## Three kinds, explicit compatibility

Transcript chunks retain their original schema, collection, version hash and v1
public evidence type. `RagAdapters.index_snapshot` accepts an explicit 02
`SourceSnapshotV2(kind="transcript")` only with the actual `TranscriptResult`;
the existing index path verifies the real content/version hash. `search_snapshots`
unwraps transcript snapshots into that same permission-fenced v1 search path.
There is no invented transcript/version for an image-only video.

OCR and visual observations use their own v3 SQLite manifest tables and Chroma
collection (`yk04_media_v3_*`). Snapshot identity includes video, generation, kind
and evidence revision. The collection fingerprint also includes the media part
format/byte cap and existing embedding fingerprint. A changed OCR revision cannot
read the preceding revision's active semantic run; another kind is not overwritten.
Long OCR is split on Unicode character boundaries into at most 6000 UTF-8 bytes
per vector part. Citations retain the original full frame text, timestamp, frame ID,
asset ID, kind and evidence version; duplicate parts collapse to one evidence hit.
No image embeddings or cloud OCR service is used.

## Trusted integration boundary

The current 02 contract authorizes v2 media only for a durable **enrichment job on
one exact video/generation**. Module 04 consumes that contract without fabricating
a chat job or widening a transcript job's frozen scope. Inside that trusted active
execution, after 02 `MediaStore.publish` has committed the actual bundle:

```python
snapshots = published["snapshots"]  # 02-owned immutable provenance, not client text
for snapshot in snapshots:
    await rag_adapters.index_snapshot(snapshot, context, semantic=False)
result = await rag_adapters.search_snapshots("ข้อความบนภาพ", snapshots, context)
evidence = await rag_adapters.evidence_media(snapshots, evidence_ids, context)
inventory = await rag_adapters.inventory_media(snapshots, context)
```

`semantic=True` additionally prepares the embedding index. `search_media` supports
`mode="auto"`, `"lexical"`, or `"semantic"`; transcript-only `search_snapshots`
uses the existing transcript search options. Do not pass a transcript DTO for OCR.
OCR/visual snapshots can be searched together inside that same enrichment scope;
mixed transcript/media or general multi-video v2 chat scopes are rejected. 02 must
first define and freeze those scopes before 04 can accept them.

The existing merged 03/05 full factory does not automatically call these new 04
methods after media publication. Its owner must wire the 02 publication handoff
and propagate `RagAdapters.provider_operations["index"]`; do not label generation
or enrichment as broker-compliant merely because 04 indexing is compliant. PRs
#25/#26 propose separate integration contracts and are not certified by this PR.
No extra HTTP routes or public filesystem directory are added by 04.

Every read, inventory, cache access, indexing checkpoint and publication checks
the live 02 durable lease, owner/account/membership, generation/deleting state and
currently selected evidence revision. The scope is rechecked after asynchronous
work. Candidates returned by Chroma must match the authorized run, part and stored
frame citation. Permission, integrity and lifecycle failures remain errors; they
are never converted to empty hits or a fallback. Images are retrieved only through
02's authorized `/api/media/assets/{asset_id}` route, which checks access again.

## Local search, coverage and safe publication

Local OCR/visual text is committed atomically before optional embedding work.
SQLite `instr(lower(text), literal_query)` searches those records with bound
parameters, including Thai substrings. It interprets neither wildcard nor FTS
operators and does not claim fuzzy/semantic equivalence. An absent semantic run
uses this path in auto mode; approved quota/policy/provider waits during query
embedding can also use it. Explicit semantic mode reports failure instead.

Results include `mode`, `semantic_complete`, `fallback_reason` where applicable,
and a limitation even when there are no hits. Receipts/inventories distinguish
prepared evidence from semantic readiness, retain sampled timestamps/duration,
mark other kinds as unassessed and always report `whole_video_reviewed=false`.
Neither all prepared vectors nor all sampled frames imply every second was seen.

Vectors remain staging until all expected part IDs exist and a final SQLite writer
fence publishes the active pointer. Failure cannot publish half an index. A newer
prepared revision retires the previous pointer even when embedding is still pending.
Reindexing the same snapshot replaces it atomically. Successful per-item embedding
cache writes are the durable checkpoints; a resumed attempt does not extract/OCR
the clip again and does not send previously successful texts again. Vector writes
may be repeated locally under a new staging run, which remains invisible until complete.

## Embeddings and the project broker

No provider request is made without a trusted execution's `gemini_call`. Both SDK
`countTokens` and the actual embedding HTTP request use 02's broker with the explicit
embedding role, exact configured model and a unique per-request call key/input hash.
SDK retries are disabled. The installed SDK expands even one Content into a batch
endpoint, so embeddings use Google's official single `embedContent` REST endpoint
over the same owned HTTPX transport. The actual endpoint equals the approved grant.

The live batch cap is deliberately **one text per embedding HTTP request**, independent
of the local transcript batching setting. This never counts a multi-input HTTP batch
as a single embedding unit. Count preflight reserves a conservative UTF-8 byte bound
plus overhead, then validates the actual positive count and 8192-token limit; the
embedding request reserves that measured count. 02 independently enforces the checked
project/model pool RPM/TPM/RPD and concurrency caps for every call. An input exceeding
the approved pool budget is rejected rather than silently changing model or billing.
This conservative first version can use more RPM and reject an estimate that would
fit after exact counting; it prioritizes explicit accounting over batch throughput.

`429` becomes `provider_rate_limited`; `503` and other server failures become
`provider_unavailable`; authentication/permanent errors remain non-retryable.
Transport/deadline failures are sanitized. REST Retry-After is passed as bounded
metadata to 02. No provider body/key/raw exception is persisted or returned. 04
does not sleep/retry around the broker: it propagates the shared error and retains
successful checkpoints so the 02 scheduler owns waiting, deadlines and consent.

Cache keys bind the actual prepared text (including title/query formatting),
purpose, provider/model, dimension, format version, full fingerprint, durable owner
and source snapshots. Cache reads reauthorize before looking up a vector, including
query vectors; a hit never grants access to a different account or revision. There
is no public cache retrieval API. Checkpoints survive process restarts via SQLite.
The approved 02 policy fingerprint is part of cache scope, so policy renewal or
returned-model review invalidates old checkpoints. 04 hashes the credential actually
captured by its HTTP client and checks it against 02's approved key fingerprint
before lookup/dispatch; a different module override cannot use another project's approval.
Count/embedding endpoints may not report a resolved model; the broker records None
in that case, not an invented returned model or a promise that an alias never changes.

Missing keys do not prevent local adapter construction/OCR search. Outbound calls
remain unavailable until key and 02's verified operator Free Tier policy/model grants
exist. No billing, tier, key/account rotation, LLM model change or paid fallback is
performed here. Existing `EMBEDDING_MODEL` stays unchanged; the adapter currently
supports gemini-embedding-2 only, and even that name is not proof of free access.

## Upgrade, deletion and recovery

Stop all API/workers and follow 02's backed-up schema-0003 migration first. With the
same selected database/Chroma settings, run additive `yk-full rag-init --workers-stopped`
or the documented direct `yk-rag init`. This adds 04 media/cache tables without
rewriting existing transcript rows/vectors or cursor keys. Restart all 04 consumers
on this version together. Older code does not know these new media tables.

The existing durable deletion adapter now removes generation-bounded media vectors,
manifests and embedding checkpoints alongside transcript indexes. It requires the
02 deleting tombstone, zero memberships and no active readers, verifies vector deletion,
and retains metadata on failure. Another subscriber's detach does not physically
delete shared assets/indexes. 02 remains responsible for original asset files.
Stopped `yk-rag gc --workers-stopped` also removes retired media runs and explicitly
requested abandoned staging, retaining active runs and deferring live readers.
Cache entries for superseded revisions remain inaccessible and are purged on final
generation deletion; monitor SQLite/disk size rather than assuming unbounded storage.
For a store that has only local lexical evidence and no Chroma pair yet, explicitly
bind the stopped store before using the existing general GC command.

Back up/restore SQLite, Chroma/marker and the 02 media asset namespace together.
No production migration, user data change or restore drill is performed by these tests.

## Validation and official references

See FREE_TIER_TEST_REPORT.md for the exact tested candidate and results. Fixtures
exercise real 02 storage/quota code, SQLite and Chroma; provider HTTP, sample frame
bytes, OCR and visual descriptions are labelled doubles. They do not certify OCR
quality, real billing/tier/model access, browser login or a complete visual product.

Public references checked on 2026-10-24:
[embeddings](https://ai.google.dev/gemini-api/docs/embeddings),
[single-item REST API](https://ai.google.dev/api/embeddings),
[project/model rate limits](https://ai.google.dev/gemini-api/docs/rate-limits),
[Free Tier pricing](https://ai.google.dev/gemini-api/docs/pricing).
The user's AI Studio project/billing status has not been inspected or changed.
