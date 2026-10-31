# Module 06 P0/P1 verification — 30 October 2026

## Re-review — 31 October 2026

Read the latest #34 review on head `7add7ca`: shared VideoPlan validation, exact-window
lookup, full citation containment and early rejection of invalid/reversed ranges were
accepted within the reviewed scope. Merged `origin/develop` before work (`9f569ea`,
already up to date). No new production change was needed in 06. Fresh focused
video-learning regressions: **23 passed**.

The remaining new finding was 07's outdated research browser flow. Its corrected
real-HTTP suite now passes **9/9** on both the module checkout and the isolated combined
snapshot. Combined Docker 07 tests pass **83**; lint/format passes **294** Python files,
with the captured source fingerprint unchanged during execution. External providers
remain fixtures, not live AI acceptance; no quota ledger or 01/03/05 source was changed.

## Review follow-up

Merged `origin/develop` (`9f569ea`, already up to date) on the module branch before
editing. Addressed #34: parse/validate the topic using 03's existing `VideoPlan` before
catalogue access or native fallback. Pass that exact point/range window to 04 and
independently require full containment of returned citations. Out-of-window/straddling
stored observations trigger native fallback; out-of-window native results are rejected
before generation. Invalid/reversed ranges fail before either path. Valid clock tokens
are removed only from the lexical lookup topic, so a range's numbers cannot suppress
relevant in-window observations; the original topic still reaches generation.

The full team already supplies the shared planner. Tests load its existing source
through explicit test-only Python paths; the Docker test allowlist/copy includes that
source. Production dependencies and lockfiles remain unchanged. Module 03 is not edited.

Latest Windows full suite: **149 passed**; focused video-learning suite: **23 passed**.
Latest Linux Docker acceptance suite: **153 passed**. The coordinated 07 store/worker/
publication suite checks valid point/range reuse, out-of-window fallback, straddling
evidence, invalid times and the separate vision model. Ruff lint/format, both lock
checks and whitespace checks pass. No live provider call was needed for this review.

Work ran on `feature/06_research_learning_agent`, updated to develop `9f569ea` before
editing. This PR changes only 06. Enable shared observation reuse by installing the
separate 04 evidence-library PR; older 04 retains the previous native fallback.

- Windows: full original-plus-P1 suite passed 132 cases, followed by seven final
  targeted cases including the added single-source guard.
- Linux Docker: **137 passed**, including all 06 tests and the 05-backed acceptance
  environment. Image `video-buddy-06-p1:test` uses target `acceptance`. Final run mounted
  this branch's source/tests read-only, disabled networking and used non-root UID
  10001, 2 GiB RAM, 2 CPUs and PID limit 256. No real key/state was mounted.
- Integration in 07: actual 02/04/06 services publish and reopen a native-cited Quiz
  without another vision call. Cold backup/restore retains the full observation after
  reuse expiry; revoking the library grant makes the saved source unavailable.
- Ruff lint/format and Git whitespace checks pass. Tests cover forged observation
  IDs, complete evidence text/replay caveats, native-vs-transcript citation kinds,
  normalized duplicate prompts, preservation of Thai tone marks and the single-source
  native boundary. Semantic duplicate detection remains a manual/model-review task.

The separately capped real-provider learning probe in 07 attempted a Quiz on a real
clip and stopped at `provider_unavailable` after two outbound admissions. Flashcards
and study plan were not attempted after that failure. No retry loop, model/key/policy
change or ledger reset occurred. P0 live learning acceptance and human educational
quality review therefore remain pending; offline schema success is not live acceptance.
