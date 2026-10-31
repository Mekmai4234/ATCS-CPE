# Feedback integration — 31 October 2026

Module 01 now uses the merged 02 CHAT_REVIEW_CONTRACT.md.

- GET/PUT/DELETE feedback uses stable assistant IDs, session cookies and CSRF.
- Shared full/floating ResultView loads current server votes; history restores message ID/visibility.
- Per-session Api context/event bus updates views; no feedback/credentials are persisted locally.
  Unmount/session changes abort reads and discard stale write callbacks. GET sequence fences
  prevent older reads replacing newer updates. Thai reason labels map to backend reason codes.
- Policy notice loads from server. When that endpoint is available, new chat submissions
  precheck the same frozen request. Warn uses native accessible confirmation and the opaque
  server token; block never calls chat. Edited draft/scope/conversation invalidates in-flight
  checks. Retries retain the original operation/key; existing backend admission remains authoritative.
- Withheld ResultView emits only a neutral placeholder, without draft/citations/feedback.
- Admin review tab uses separate audited list/detail/PATCH routes; it never reads private
  member conversations. SQL pagination/filter params, explicit review outcomes, expired/
  forbidden states and separate restricted draft display are supported. Content is text-escaped.

Validation: 125 unit tests, TypeScript. Actual checkout real-HTTP identity regression 9/9 passed, including added real feedback/block/warn/admin workflow after a label fix.
Only external Google/model providers are fixtures; application HTTP, cookies, CSRF,
SQLite migrations and worker are real. All state is isolated in 01/runtime.

Resume UI checks existing replacement before prechecking new admission; two API regressions verify replay/no prompt and fresh acknowledgement mapping.

Remaining acceptance: expired warn-token/resume end-to-end, cross-session delayed-write and
withheld end-to-end corpus, explicit admin access-revocation/expiry UI regression, full
merged-source CI, final human copy/privacy review and deployment. Existing moderation
and retention are backend-owned; no actual user DB migration/capability toggle/deploy.
02 now provides the private, attempt-bound v1 answer-signal sink; 05's producer
remains unmounted. Its policy is separate from chat-local-v1, and experimental v2
is not accepted by the v1 sink. No live AI quality/latency/SLA claim.

## Final local verification

125 unit tests; Buddy browser 18 passed; feedback browser 2 passed after replacing
a timing-sensitive 150ms assertion with a deterministic fixture release event.
Actual-checkout identity E2E 9 passed; added feedback/moderation/admin case rerun on
final source passed, including real mobile font-size/overflow assertions. Typecheck,
production build and Prettier passed. Images in docs/screenshots/chat-review-*-2026-10-31.png
use only fixture members and synthetic provider content over real HTTP/SQLite/worker.
CI for this new PR and integrated release acceptance remain pending.

## Integrated acceptance fixes

The module 03 regression now verifies both shared-import dependency scheduling
orders without assuming which concurrent account won the import. Module 07 runs
web/deployment identity projects against separate real API/worker/databases so
unrelated test sign-ins do not exhaust the shared IP challenge budget. Production
authentication limits, lease fencing and real HTTP/CSRF checks are unchanged.
All 11 integrated identity scenarios pass locally (web 9, deployment 2), with
separate diagnostics and verified process cleanup. The exact combined source must
still pass all CI jobs before merge; no live provider/deployment claim is made.
