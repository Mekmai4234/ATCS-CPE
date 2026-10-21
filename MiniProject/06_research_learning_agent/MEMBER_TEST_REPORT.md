# Module 06 member execution verification

Verified 2026-10-21 (Asia/Bangkok). Base: develop `69f5347`.
Only module 06 files are changed. Dependency manifests, locks and other modules are unchanged.

## Changes

- Bind research/learning execution to 02's durable actor and authorized source contract.
  Authenticated calls automatically use the guard even through 05's direct AgentService composition.
- Recheck permissions before/after bounded tools/models, before events and before final,
  partial or artifact delivery. Denial aborts without returning previously obtained evidence.
- Add a backend-injected authority/permit interface and an explicit fail-closed member factory.
- Add atomic per-owner concurrency reservations and persisted operation counters in the
  module-owned agent06_permits table. Default: two active executions and 64 bounded operations
  per execution attempt. Reopening the same lease cannot reset budget; stale leases are reclaimed.
- Preserve existing cancellation, deadlines, steps, citation checks, packaged dataset and
  isolated 05 acceptance environment. Add two-account/revocation fixtures and contract tests.

## Results

| Environment | Result |
|---|---|
| Windows core environment | 96 passed |
| Windows combined core + real 05 acceptance environment | 100 passed |
| Docker latest core target, updated recovery assertion via read-only tests mount | 96 passed |
| Docker latest combined acceptance, including updated recovery assertion via read-only tests mount | 100 passed |
| Pending 02 member contract, isolated snapshot on Windows | 4 passed |
| Pending 02 member contract, isolated snapshot mounted into latest Docker image | 4 passed |
| Ruff lint/format (all module Python source and test directories) | passed |
| Core and acceptance uv lock --check --offline | passed; no dependency metadata changes |

The 21 member tests cover foreign source/job denial, admin labels, revocation during
search/read/inventory/evidence/model execution, suspension during all three artifact types,
independent shared-source membership, cancellation, partial coverage, account switching,
identity mutation, per-owner quotas, duplicate-lease denial and stale-lease recovery.
Real 05 comparison acceptance tests cover both successful member execution and revocation
inside its provider callback, preventing another generation and any published result.

The optional backend contract suite used an unmodified snapshot of
origin/codex/02-google-auth-ownership at `f406d326a8545d1f2468a7ea3c074c5144a80a9b`.
It tests actual 02 HTTP/session/SQLite/worker ownership checks with fixture Google/provider
responses. Assertions include foreign-source submission denial, foreign research/events/cancel
denial, foreign artifact read denial, successful owned research/quiz persistence, account
suspension/source revocation, and expired-cookie background completion with API read returning 401.
It uses fixture knowledge backed by 02's indexed fixture chunks, not live Gemini/YouTube.

## Migration, dependencies and limits

No existing table is altered and no legacy content owner is assigned by 06. The new permit
table is initialized additively under backend write transactions on first member execution.
Back up the backend database before rollout; rolling back leaves this table unused.
Cross-worker admission and counters use 02's serialized SQLite write boundary, not process-local slots.

Member deployment depends on 02 PR #18 and authorized retrieval from 04 PR #20. The latter
contract was inspected at `d4aa52d137b44f9217923bd18afc77b6a00881ef`, but a fully merged
02/04/05 member deployment and frontend account-switch UI were not tested in this round.
Existing develop has no member HTTP/schema contract; enabling auth with missing contracts
fails closed. Legacy offline composition remains available and is not a multi-account deployment.

02 remains responsible for ownership on list/read/download/resume/cancel/events APIs and
atomic publication checks; 01 clears UI subscriptions/results when switching accounts.
06 does not introduce a new download/resume/SSE route, Google credentials or frontend changes.
The policy bounds concurrent executions and calls per attempt; it is not a daily token/billing quota.

Early new-test failures exposed test expectations that confused completed tool progress with
final run progress, fixture chunk IDs that did not match backend publication validation,
and Python import path ordering in the optional Docker contract suite. These test fixtures
were corrected; the final runs above passed without skips or test exclusions.

Local XML evidence and the dependency snapshot are ignored under runtime/. No runtime
database, credential, snapshot, virtual environment or generated cache is included in the PR.
