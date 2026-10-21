# Acceptance matrix and AI evaluation

Offline evidence uses provider/model doubles with actual application services and data
stores. `tests/test_system.py` combines real 03 normalization/ingestion orchestration,
04 Chroma, 05 answers/analysis and 06 tool loop with 02 HTTP/worker/SQLite via ASGI in one
process. Separate-container and browser behavior need separate evidence.

| Scenario | Automated evidence | Additional release evidence |
|---|---|---|
| Captions, no captions, unavailable, duplicates | 03 tests, 02 tests, 07 system flow | Thai/English real videos with provenance |
| URL → transcript → index → chat → timestamp | 07 flow, 05 integration | Live smoke, inspect cited words/times in actual video |
| Unsupported question | 05 answer tests, 02 API tests | Ask a question absent from ALL selected videos |
| Scope/channel/date/invalid filters | 02 boundaries, 04 RAG, 05 integration | No unselected-video evidence |
| Summary/comparison coverage | 05 paginated/batched analysis | Review selected videos, missing coverage, contradictions |
| Agent tools/budgets/partial/learning outputs | 06 tests, 02 integration, 07 comparison | Inspect plans, quiz explanations and flashcards |
| Timeout/retry/cancel/delete/restart | Existing integration and 07 regressions | Separate-process restart with no stale publication |
| Backup/restore | 07 actual SQLite/Chroma recovery | Operational live-pair restore/inventory/citation check |
| Browser import/library/chat/seek/errors | Pending 01 application | Browser E2E and keyboard flow |

## Human review protocol

Fix the dataset BEFORE scoring. For each case record case ID, video ID/URL, language,
caption source/date/version, supporting text/time intervals, question/task, scope,
expected answer or abstention and reviewer. Include Thai and English captioned videos,
missing captions, duplicate, unavailable, unsupported question and a two-video comparison.

Save outputs in ignored 07/runtime. Compare each factual claim with its cited passage;
valid citation IDs alone do not prove support. Record supported/inspected claims,
correct/inspected citations, reference retrieval recall at a stated k, unsupported-question
abstentions and processed/expected chunks/videos. Review contradictions, translation,
Thai readability, quiz explanations, prerequisites and dates. A human records pass/fail
with reasons. Do not invent quality thresholds after seeing results.

Measure import/answer latency separately, include failures/timeouts and dataset details.
Record requested/returned model, exact provider usage if returned, index fingerprint,
SDK/lock version and commit. Hash-vector retrieval is not semantic evaluation. Missing
token/cost data remains unavailable, not zero or an estimate presented as measurement.

## Operations and release gate

Correlate logs/errors with request/job/run IDs. Capture job stages/retries, worker
completion, provider errors, agent tool counts and citation failures from existing job
results/logs. Do not log credentials or unnecessary full transcripts. No new metrics
server, alerting deployment or performance result is claimed.

Release requires baseline, known-defect regressions, recovery, actual container/live
acceptance, human AI review and web flow. A green subset or /health alone is insufficient.
