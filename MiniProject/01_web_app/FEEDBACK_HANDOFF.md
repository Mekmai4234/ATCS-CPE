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

Validation: 123 unit tests, TypeScript. Actual checkout real-HTTP identity regression 8/8
passed; added real feedback/block/warn/admin workflow passes separately after a label fix.
Only external Google/model providers are fixtures; application HTTP, cookies, CSRF,
SQLite migrations and worker are real. All state is isolated in 01/runtime.

Remaining acceptance: expired warn-token/new resume UI, cross-session delayed-write and
withheld end-to-end corpus, explicit admin access-revocation/expiry UI regression, full
merged-source CI, final human copy/privacy review and deployment. Existing moderation
and retention are backend-owned; no actual user DB migration/capability toggle/deploy.
05 signal ingestion still needs a separately versioned owner-02 sink; do not assume
chat-local-v1 accepts new answer-signal metadata. No live AI quality/latency/SLA claim.
