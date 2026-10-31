# Module 04 P1 verification — 30 October 2026

## Re-review — 31 October 2026

Read the latest #33 review on head `87babfc`: effective vision model reuse and its
ownership/version/expiry safeguards were accepted within the reviewed scope. The
remaining new blocker is in 07's real HTTP research browser test. Merged
`origin/develop` before work (`9f569ea`, already up to date); no new production change
was needed in 04. Fresh catalogue regressions: **12 passed**.

With the corrected 07 test, the isolated combined snapshot passes **9/9** real-HTTP
browser cases, **83** Docker 07 cases, and lint/format for **294** Python files. Source
fingerprinting was verified unchanged before/after the run. No 01/03/05 source was
edited by this follow-up; GitHub CI on the separate PR heads remains a distinct gate.

## Review follow-up

Merged `origin/develop` (`9f569ea`, already up to date) on the module branch before
editing. Addressed #33's model mismatch: native catalogue reads now use the same
effective model as the native writer, `vision_model or llm_model`, while retaining
owner/source/generation/version/prompt/expiry fences. Regressions cover the default,
a separate vision model and a subsequent model change invalidating reuse.

Latest Windows catalogue suite: **12 passed**. Latest Linux Docker full suite:
**171 passed, 1 existing live embedding test skipped**. Full Ruff lint/format and
whitespace checks pass. The coordinated 07 test additionally checks native learning
reuse with a separate effective vision model. No 01/03/05 source was edited.

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
