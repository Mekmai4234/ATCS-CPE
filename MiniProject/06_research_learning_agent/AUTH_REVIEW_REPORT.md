# Module 06 auth integration review fixes

Verified 2026-10-22 (Asia/Bangkok), addressing the supplied 06_review_and_fixes.md.
Only module 06 source, tests, Docker configuration, documentation and its two locks change.

## Candidate provenance

Base develop: `69f534730669f59051a453d9833a0be88695f263`.
The common disposable candidate uses unmodified Git archives of:

| Module / PR | Revision |
|---|---|
| 02 / #18 | b047e809f983ffb2e4f3f9d3e3f074b8976cd6da |
| 03 / #19 (available for composition, not a 03 regression gate) | c3c7c598ae2f6692d360c8cd5d8d6aacc1e6fc04 |
| 04 / #20 | 1c1c536de3d2a316cc239b8f21b186cd8169aff8 |
| 05 / #23 | 144d2b14848bec0085f2ff9d0cee6453e9ba1391 |
| 06 / #21 | 84fb1b6 plus the review fixes in this change |

These are the refreshed auth dependency heads, rather than the older heads in the
2026-10-21 review. Core, acceptance, backend contract and Docker use this same candidate.
Other modules are neither checked out over the user's files nor edited. Archives and
runtime evidence stay ignored under runtime/auth-review-candidate and runtime/.

## Fixes

- Evaluation now defaults explicitly to authenticated execution in a NEW isolated
  database. A synthetic active user owns imports, durable jobs and artifacts through
  02's server actor context. The actor context is restored on completion/failure.
- Reports label isolated-member-fixture. Explicit --legacy-test supports offline
  regression only in another NEW isolated database, labels isolated-legacy-test,
  and is rejected with --live before state/provider creation. Production auth is unchanged.
- Authentication/authorization errors cannot satisfy a dataset's expected failed state.
  A negative test exercises this through the real worker; no auth exception is suppressed.
- HTTP fixtures use 02 challenge, nonce, session cookie and CSRF, with fixture Google
  claims. Direct test setup/assertions use an explicit scoped actor helper; worker and
  HTTP ownership checks remain real. Resources close even when HTTP login/import setup fails.
- Real 05 comparison now uses actual backend membership instead of a fake authority.
  Revocation inside generation prevents another generation and any published output.
- Added A/B research/events/artifact/cancel checks and publication-fence tests for both
  research and direct artifacts. They revoke access after a valid Agent result exists
  but before 02.finish enters its write transaction, proving no result/artifact persists.
- Refreshed core and acceptance locks against 02's google-auth/requests metadata.
  Existing package pins and 06 public dependency metadata are unchanged. No other lock changes.
- Added an explicit Docker contracts target/service alongside core and acceptance.

## Verification

| Gate | Result |
|---|---|
| Windows core, locked core environment | 102 passed |
| Windows combined core + real 05 acceptance, locked acceptance environment | 106 passed |
| Windows optional backend contract, same candidate | 4 passed |
| Core and acceptance uv lock --check --offline | passed |
| Core and acceptance uv sync --locked --offline | passed |
| Docker build: tests, acceptance, contracts | passed |
| Docker core | 102 passed |
| Docker combined acceptance | 106 passed |
| Docker backend contract | 4 passed |
| Evaluation CLI, authenticated default, Windows | passed, 6 cases |
| Evaluation CLI, explicit isolated legacy mode, Windows | passed, 6 cases |
| Evaluation CLI, authenticated default, Docker | passed, 6 cases |
| Evaluation CLI, explicit isolated legacy mode, Docker | passed, 6 cases |
| Ruff lint/format (Windows and Docker) and Docker Compose config | passed |

An earlier overlapping Windows run had one fixture import that did not reach ready.
The isolated case and subsequent serial full runs passed; timeouts were not increased
and failing cases were not excluded. A later negative evaluation case is included in the
final counts above. Docker initially had no working engine; verification resumed after
the user reopened it. Earlier Docker evidence from the original PR is not substituted.

Windows JUnit evidence: runtime/review-core-local.xml, review-combined-local.xml and
review-contract-local.xml. Docker output: runtime/review-core-docker.log,
review-acceptance-docker.log and review-contracts-docker.log. CLI JSON reports use
runtime/auth-cli-member-20261022.json and auth-cli-legacy-20261022.json.

## Reproduction and remaining boundaries

Assemble the recorded dependency heads with this module's working tree in a disposable
MiniProject layout, then use its 06 project paths for:

```powershell
uv lock --project 06_research_learning_agent --check --offline
uv lock --project 06_research_learning_agent/acceptance --check --offline
uv sync --project 06_research_learning_agent --locked
uv sync --project 06_research_learning_agent/acceptance --locked
uv run --project 06_research_learning_agent --locked pytest 06_research_learning_agent/tests -q -W error
uv run --project 06_research_learning_agent/acceptance --locked pytest -c 06_research_learning_agent/acceptance/pyproject.toml 06_research_learning_agent/tests 06_research_learning_agent/acceptance/tests -q -W error
docker compose -p yk06-auth-review -f 06_research_learning_agent/compose.test.yaml build tests acceptance contracts
docker compose -p yk06-auth-review -f 06_research_learning_agent/compose.test.yaml run --rm tests
docker compose -p yk06-auth-review -f 06_research_learning_agent/compose.test.yaml run --rm acceptance
docker compose -p yk06-auth-review -f 06_research_learning_agent/compose.test.yaml run --rm contracts
```

The old unauthenticated develop dependency metadata does not satisfy these refreshed
locks. Merge/test the dependency batch together; do not regenerate against old develop
or disable application auth to conceal the mismatch. The existing module-owned permit
table remains the only 06 runtime schema addition; this review introduces no new migration.

All Google/provider responses are fixtures; real Google/browser login, paid Gemini,
semantic quality and a production auth release were not verified. The synthetic
evaluation owner is not a verified Google account or a legacy-data migration policy.
This is module 06 integration evidence, not an all-module combined release gate.
