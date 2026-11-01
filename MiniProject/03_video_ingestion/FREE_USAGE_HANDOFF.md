# Free usage plan — module 03 — 1 November 2026

Phase1: added content-free caption timing diagnostics: segment count, exact repeated
text/interval count, overlap count and union duration. Duplicate/overlapping intervals
do not inflate covered seconds; repeated words at different times are preserved.
Diagnostics do not remove source segments or claim missing time contains speech.
Without trusted video duration no trailing completeness is inferred.

Existing backend worker already commits metadata and normalized captions before
indexing and reloads that checkpoint on retry. New integration regressions exercise
both automatic retry and exhausted-attempt manual HTTP retry with real isolated
SQLite/API/worker/Chroma: the same frozen source/transcript is indexed, YouTube
metadata/caption clients cannot be called again, and readiness occurs only after
index receipt/inventory match. No second cache or retry loop was added in03.
Existing member scheduling tests cover duplicate imports and access isolation.
Provider errors distinguish missing captions, unavailable/restricted video,
network timeout/block, rate limit and failed indexing; retries remain worker-owned.

Phase2: indexing already consumes TranscriptResult rather than downloading video.
The checkpoint retains caption source (manual/generated), language, source generation,
transcript version, segment IDs and timestamps. Owner04 must implement the local
embedding provider/index version and migration; no04 files were changed here.
ASR/OCR are separate opt-in paths, not a promise that every YouTube link is accessible.
No ASR model, local embedding index, real-video completeness/quality benchmark or
production migration is included. No paid API, live provider or user DB was touched.
