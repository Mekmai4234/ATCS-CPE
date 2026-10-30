# Module 04 P1 verification — 30 October 2026

Work ran on `feature/04_rag_knowledge`, updated to develop `9f569ea` before editing.
This PR changes only 04 and uses the existing 02 immutable stores/contracts; no new
dependencies, schema migration or paid/provider requests are needed for catalogue reads.

Linux Docker full suite: **169 passed, 1 skipped**. The skip is the existing live
embedding acceptance test requiring an approved durable backend execution. Image
`video-buddy-04-p1:test` was built from 04/Dockerfile; final source/tests were mounted
read-only, with networking disabled, UID 10001, 2 GiB RAM, 2 CPUs and PID limit 256.
The earlier Windows full run passed 168 cases before the late-interval regression was
added; the final ten catalogue cases were also run on Windows. Ruff lint/format and
Git whitespace checks pass. The test_rag.py change is formatting only.

New checks cover different questions reusing the same full native observations without
embeddings, irrelevant-question misses, another owner attached to the same clip,
reuse expiry, revoked grants, changed generations, OCR snapshot provenance, balanced
multi-source transcript retrieval, time filtering, bounded request validation, and a
relevant late transcript chunk found with a one-record collection budget. Citation
intervals remain their original overlapping intervals, rather than fabricated clipped
times. 07 additionally verifies 02/04/06 publication/history and cold restoration of
expired-but-referenced native observations.

07 measured actual local retrieval on one existing real RAG clip: first 39.52 ms,
repeated-question p50/p95 23.66/24.21 ms (n=20), different-question p50/p95
26.06/29.42 ms (n=20), zero provider calls. This is local catalogue latency after
startup, not full answer latency or a semantic retrieval-quality score. Fixture tests
measure mechanics and expected evidence IDs; human real-content review remains pending.

05 integration belongs to its owner. 06's separate PR consumes current native records;
OCR/visual v2 records remain distinct and are not forged into transcript citations.
