# Local embedding boundary — 2026-11-01

Merged develop `9aca742` before work. Depends on module 02's pinned private local
broker; this PR changes module 04 only relative to its module-02 base.

Set `EMBEDDING_PROVIDER=ollama`, `EMBEDDING_MODEL` and `LOCAL_EMBEDDING_MODEL`
to the same reviewed installed model tag; set `LOCAL_EMBEDDING_DIGEST` to its
64-character `/api/tags` digest and `EMBEDDING_DIMENSIONS` to measured output size.
The RAG factory selects `OllamaEmbedder`. It requires a current trusted execution,
uses 02's local broker rather than Gemini policy, preserves prepared Thai text,
and rejects malformed, zero, non-finite, mismatched-dimension or wrong-size output.
The broker disables embedding truncation. Batch and input byte limits remain bounded.

Collection fingerprint and the existing private embedding checkpoint key include
provider, model, dimensions, digest, chunking and text preparation version. Gemini
and fixture fingerprints remain unchanged. No cross-model vector search or reuse
is allowed. Existing source-generation, transcript-hash, atomic publication,
current grants, deletion, cursor and final inventory checks still apply.

Existing short-context reading uses complete scoped transcripts only when the
bounded corpus fits; existing lexical evidence-library and vector retrieval paths
remain available. These mechanism tests are not a measured Thai retrieval-quality
comparison and do not select a winning local model.

## Migration boundary

Do not change provider against the existing production store and assume rollback
is free: the current manifest has one active run per video/generation and ordinary
reindex cleanup retires/removes prior vectors. Preserve a stopped, paired SQLite /
Chroma / media backup first. Trial a separate copied DB/store with the same logical
database namespace before any cutover, inspect count/inventory/citations, then use
an explicit coordinated deployment with jobs drained. Restore the paired backup
and old configuration/image to roll back. Never mix a copied Chroma store with an
unrelated DB or expose copied private evidence to another account.

Fresh import execution can use the new local embedder. The stopped-maintenance
CLI has no authenticated local execution context and therefore cannot yet run
local inference; it fails closed. A background reindex/cutover API preserving the
old active index, production ingestion/team-05 mounting, actual Thai embedding
benchmark and real model migration remain pending. No production index was rebuilt.

Human-gold remains pending by user instruction. Local HTTP/vector fixtures verify
the boundary and namespaces; they do not establish semantic quality or model capacity.

API reference checked 2026-11-01: https://docs.ollama.com/api/embed
