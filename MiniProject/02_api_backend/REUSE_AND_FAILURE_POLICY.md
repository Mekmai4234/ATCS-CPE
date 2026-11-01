# Persisted answer reuse and failure policy

Current implementation uses committed job results, not a second answer cache. Lookup is
inside the worker: at most 100 completed jobs from the same owner in the last 24 hours.
History remains readable after that lookup window. No new workload evidence justifies
changing retention or adding an index in this change.

The trusted producer supplies a SHA-256 signature over owner-isolated sources, request,
history, generation/retrieval configuration and policy versions. Backend additionally
requires exact frozen sources/history/request (excluding conversation ID) and execution
identity. Only published, answered, cited transcript results with valid schema/metadata
qualify. Malformed candidates miss; current source/role/session checks still fail closed.
The consumer must revalidate every citation against the current index before publication.
Reuse returns the answer payload without original conversation/message/feedback IDs.

## LIMIT-01: API fast path design (not enabled)

Use an explicit trusted adapter `lookup_only` contract carrying the same signature and
validator; never run the generating adapter in a fast path. Admission, moderation and
owner/source/config validation must precede lookup. Within one database transaction,
recheck current source/role state, bind the new/replayed job and publish through the
existing publication path, producing exactly one assistant message for that job.
Feedback stays bound to its original message. A new question gets its own message;
replaying the same idempotency key returns the same job/message. Worker absence must
not bypass readiness, authorization or evidence validation. A miss queues normal work.
Before enabling: actual HTTP tests with worker stopped, stale indexes, revoked session,
double click, concurrent submit, publication failure and transaction rollback are required.

## LIMIT-03: single-flight design (not enabled)

Coalescing is permitted only for equal owner, frozen sources, normalized request, history,
execution/config/policy signature. Never merge across owners or continuation contexts.
Use durable job state as the leader record with a bounded lease; followers retain their
own authorization, job IDs and publication transaction. Canceling a follower detaches it;
it must not cancel the leader. Leader failure propagates its typed failure, not a synthetic
success. Lease takeover after restart must fence the previous worker before dispatch;
uncertain sent usage is not refunded. Recheck all sources/citations when publishing each
follower. No automatic fresh generation for regenerate or bypass-cache jobs.
Implementation needs explicit leader lease, follower cancellation and restart regressions
first; this document does not claim calls saved by coalescing or worker-free reuse.

## Error contract

| Condition | Behavior | Retry owner |
|---|---|---|
| provider 503 / transport failure | safe provider-unavailable error; retain sent/uncertain accounting | bounded job policy |
| provider 429 | preserve rate-limit and valid retry-after | broker/job policy, no stacked SDK retry |
| provider quota/policy unverified | durable paused/wait state; no dispatch without grant | explicit resume after eligibility |
| request/provider timeout | bounded deadline; uncertain sent reservation stays accounted | bounded job policy |
| probe budget | stop the probe, retain failure/partial evidence | no retry to select better output |
| invalid schema/citations | reject publication | no repair loop or silent success |
| revoked source/session/role or lost lease | fence execution/publication | never retry past guard |

Offline fault tests use temporary state and simulated clocks. Never reset a real quota
ledger, move credentials/projects or dispatch from a copied provider ledger.
