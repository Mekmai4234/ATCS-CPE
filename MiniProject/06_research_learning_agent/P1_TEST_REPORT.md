# Module 06 P0/P1 verification — 30 October 2026

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
