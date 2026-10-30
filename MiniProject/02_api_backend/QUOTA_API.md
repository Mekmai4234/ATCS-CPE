# P1 quota and restart contract (30 October 2026)

`GET /api/quota` requires an active member session. `GET /api/admin/quota`
additionally requires an administrator. Both are read-only, `Cache-Control: no-store`,
and make no provider requests. Responses contain `accounting_source=local_ledger`,
`provider_balance_verified=false`, `observed_at`, `worker`, `status`, `reason`,
`pools` and `admission_guaranteed=false`.

Each pool contains `bucket`, `status`, `usage` (requests in rolling 60 seconds / 24
hours and input tokens in 60 seconds), and `blockers`. Member usage counts only that
member. Shared exhaustion may be reported, but other members' usage, identities,
jobs, project identifiers, keys and policy attestations are never returned. Only
administrators receive project totals, configured limits and remaining local daily
requests. Count-token calls have their own admission limit; they do not consume
inference daily usage. Cancelled and expired undispatched reservations are excluded;
completed, sent and uncertain calls remain counted.

Blockers distinguish local daily/request/token/concurrency budgets from provider
circuits. `time_source=estimate` uses `estimated_retry_at`; a provider Retry-After
uses `time_source=provider` and `retry_at`. These timestamps are not a Google balance
or reset guarantee. Unknown/expired/mismatched policy reports `unverified`. Worker
readiness is independent of quota availability. A status read does not reserve capacity;
the broker still checks exact input size, role, FIFO and policy at dispatch.

`POST /api/jobs/{job_id}/resume` uses the existing session/Origin/CSRF checks and
returns the ordinary 202 Accepted contract. Failed retryable chat, analysis, artifact
and research jobs can explicitly start one replacement after local policy/budget is
available. It preserves the frozen source versions and history, checks current grants,
and rejects a busy conversation. Repeated calls return the same replacement, including
after completion; a retry of that replacement requires its own ID. Original audit rows
and all quota ledger entries remain unchanged. Import/delete/enrichment retain their
existing retry contract. No automatic model request is made by this endpoint.

## Evidence retention and handoff

The existing `youtube-video-v1` analysis store already separates immutable revisions
from expiring lookup pointers. Lookup/reuse lasts one hour; expiry does not delete a
revision or break old citations. Citation resolution rechecks member, library grant,
generation, transcript version and exact observation interval, even after cache expiry.
Deletion/revocation makes sources unavailable rather than authorizing reuse. No new
retention cleanup is introduced. Cold backup must retain SQLite (including revisions,
lookup pointers, observations and the ledger), Chroma and referenced media together.
04 may search immutable observations for different questions, but only within their
reuse lifetime and the current execution scope. 05 remains responsible for deciding
whether those observations support an answer; 06 validates the supplied evidence IDs.

This PR changes only module 02. UI integration belongs to 01; shared evidence retrieval
and learning integration are separate 04/06 PRs. No schema migration or ledger reset.
