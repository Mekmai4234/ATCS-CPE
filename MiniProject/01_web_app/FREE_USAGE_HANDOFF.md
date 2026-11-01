# Free usage plan — module 01 — 1 November 2026

## Delivered

- My Jobs drawer reads the existing authenticated GET `/api/quota` on open and on
  explicit refresh. It identifies local-ledger/member accounting, observation time,
  rolling24h/60s counters and verified blocker reasons. Local RPD/RPM/TPM labels
  only follow explicit backend reasons. An upstream429 without a dimension is not
  guessed to be daily exhaustion. These are not Google remaining balances.
- Provider-supplied retry times are distinct from system estimates. Estimates do
  not disable recovery; presentation-bridge times without provenance are estimates.
  Neither time promises admission. Refresh errors discard the previous snapshot;
  closing/session unmount aborts reads. No localStorage/cache persists quota data.
- Known internal-budget/provider/worker/local-service/source/YouTube-access errors
  have distinct copy, without exposing upstream exceptions or secrets.
- Results and audited admin details share provider/model/observed-latency display.
  Gemini, Ollama, cached, fixture and system output are distinguished only when
  metadata exists; unknown provider stays unknown. Withheld output still exits
  before content/metadata/citations/feedback. No provider chooser was invented.
- Existing recovery opens import results in the library, follows saved work and
  replacement jobs, restores quiz answers and reads history without resubmission.
  The affected browser regressions, including mobile/keyboard/reload, were rerun.

## Still requires coordinated work

- Owner02: provider/model/version pinned requests, original provider on cache hits,
  authoritative quota source/dimension/observed time, local loading/health/queue and
  local-aware resume/admission. The member endpoint currently reports rolling24h
  internal counts; this UI does not relabel them as Google's Pacific calendar day.
- An explicit regenerate/cache-bypass contract is required before a truthful
  “generate new” action can bypass answer reuse; submitting a new idempotency key
  alone does not guarantee this. No ineffective button was added.
- Local streaming is not enabled. Feedback remains attached to a persisted assistant
  message. No synthetic loading percentage or automatic Gemini fallback is shown.
- History metadata omitted by the backend cannot be reconstructed by the client.
  Local/Gemini model quality, hardware throughput and paid-provider acceptance are
  not established by fixture UI tests. No billing/config/user-database changes.

Validation: unit139, affected recovery/admin browser19, TypeScript, production build
and Prettier passed. A separate real HTTP quota smoke uses isolated SQLite, real
backend auth/session and fixture identity/provider; its result is recorded in PR.
No source files outside module01 were edited. Merge develop precedes this work.
