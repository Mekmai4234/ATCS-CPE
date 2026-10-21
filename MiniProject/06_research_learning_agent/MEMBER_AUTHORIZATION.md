# Member research and learning boundary

Module 06 consumes the durable actor/source contract from module 02. It does not
implement Google verification, sessions, HTTP ownership, database ownership migration
or frontend account switching. Those remain backend/frontend responsibilities.

## Integration

`AgentService.research` and `artifact` automatically enter member execution when
`context.settings.auth_enabled` is true, including instances constructed by module 05's
team factory. `BackendMemberAuthority` uses the pending module 02 contract:

- `ExecutionContext.user_id`: durable job owner, independent of browser cookie expiry.
- `authorize_sources(sources)`: frozen job source scope.
- `check()` / `repository.check_execution(job_id, lease_token)`: lease, cancellation,
  active account and current library access. These checks must continue to enforce
  current grants, not merely replay the original request scope.
- The account-aware `jobs.owner_id` schema and the repository database read interface.

Missing member contracts fail closed. The existing legacy path is retained for current
develop's offline/single-user composition. Do not expose it as a multi-account deployment.
The explicit `create_member_adapters` entrypoint additionally requires server-injected
`repository.agent_authority`; it refuses startup without that authority before creating
the Gemini client. No request/model field selects an authority or supplies an actor.

A backend may inject a `MemberAuthority` using `repository.agent_authority` or
`MemberAgentService(agent, authority)`. `open(context, sources, kind)` must verify the
durable owner, exact generations/versions, account status, source membership and job kind.
It returns a permit with immutable `actor_id`, synchronous `check()`, `consume()` and
`close()`. A custom authority must reserve/release concurrency atomically across workers
and charge shared quotas atomically; it must clean up a reservation itself if open fails.

## Checks and revocation

MemberContext forwards the original backend execution attributes to 04/05 and checks the
bound identity and full source set at every controller check, before/after bounded
tools and model calls, before events, and before returning final/partial/artifact output.
Every bounded operation also spends an allowance before invoking its callback. Model
arguments cannot change actor or enlarge the controller's frozen scope.

Authorization denial is latched. Revoking any source or suspending an account aborts the
whole execution and discards the candidate output; 06 does not return excerpts from a
revoked source as partial results. Existing cancellation and time/step limits still apply.
Removing A's membership does not revoke B's independent membership in the same source.

The built-in policy atomically reserves up to two research/artifact execution slots per
owner in the module-owned `agent06_permits` table in the backend SQLite database.
The additive table is initialized on first member execution under 02's write transaction;
no existing table or ownership data is migrated. All processes share these reservations.
Excess jobs fail closed; this is admission control, not a separate queue or scheduler.
Each execution attempt permits at most 64 durably metered bounded operations, alongside the existing
step/time bounds. Thus admitted attempts have a bounded aggregate operation allowance;
this is not a daily billing/token quota. Configure a stricter policy by injecting
`BackendMemberAuthority(max_concurrent=..., max_operations=...)` or a backend quota authority.
02 owns retries and durable job lease release. A finally block releases the permit slot;
the next admission removes stale rows whose backend lease is expired, replaced or terminal.
Reopening the same job/lease cannot reset its allowance. Preserve this table in backups;
rollback may leave it unused. No destructive migration is needed.

Background work can continue after cookie expiry only while its durable account and
source permissions remain valid. Every API read/list/download/events/resume/cancel must
independently authenticate the current session and enforce ownership in 02. Admin does
not imply private-content access. Persisting output must recheck within 02's transaction;
a pre-return check in 06 cannot replace that publication fence or retract bytes already
delivered. Account switching must clear subscriptions and visible results in 01.

## Tests

From MiniProject, run the existing locked core/acceptance environments and Docker targets:

```powershell
uv run --project 06_research_learning_agent pytest 06_research_learning_agent/tests -q
uv run --project 06_research_learning_agent/acceptance pytest -c 06_research_learning_agent/acceptance/pyproject.toml 06_research_learning_agent/tests 06_research_learning_agent/acceptance/tests -q -W error
docker compose -f 06_research_learning_agent/compose.test.yaml build tests acceptance
docker compose -f 06_research_learning_agent/compose.test.yaml run --rm tests
docker compose -f 06_research_learning_agent/compose.test.yaml run --rm acceptance
```

The optional `acceptance/backend_contract` suite explicitly requires module 02's member
branch source, migrations and identity test fixture. It is outside the legacy testpaths,
not silently skipped. Point PYTHONPATH to a separate checkout/snapshot's backend src and
tests plus 06/tests, then run:

```powershell
$env:PYTHONPATH = "$coreTests;$backendRoot/src;$backendRoot/tests"
uv run --project 06_research_learning_agent/acceptance pytest 06_research_learning_agent/acceptance/backend_contract -q
```

The tests use real 02 HTTP/session/SQLite/job/ownership checks with fixture Google/provider
responses. The regular acceptance environment additionally tests real 05 comparison
with 02/04 and a fixture member authority, including revocation inside generation.
See MEMBER_TEST_REPORT.md for the exact dependency revision and verified scope.
