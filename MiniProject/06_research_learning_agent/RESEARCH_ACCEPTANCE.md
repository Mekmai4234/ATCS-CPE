# Research and learning acceptance

Tool reads and model calls use separate budgets. The final decision step now requests
only `finish_research`, even if model-call budget remains. Successful last calls count
their usage and observed evidence before returning partial on a budget exit.

Local research reserves synthesis plus final evidence/inventory validation. If synthesis
times out, is unavailable/busy or waits for quota after evidence collection, it returns
explicitly labeled source excerpts with partial state and zero analyzed chunks. Source
revalidation still runs; revoked, changed or canceled executions cannot publish partial
findings. Malformed output and unsupported errors remain errors. No repeated model call
or quota reset is introduced. Existing successful-input checkpoint keys still distinguish
request/source/config and explicit fresh jobs; restart reuses only the matching result.

Unit/fault regressions and 07 team-composition learning/grading matrices use scripted
providers. They verify schema, exact day count, citations, persisted readback, intentional
regeneration, submission idempotency, blank-answer zero credit and provider-failure state.
They do not certify the correctness of Thai paraphrases or a real model's grading.

Live success for quiz/flashcards/study plan, useful research synthesis and reviewed quiz
rubrics remain pending human gold and a bounded real-provider acceptance batch. Keep
failed/partial/uncertain usage and probe caps in that evidence; do not retry to cherry-pick.
