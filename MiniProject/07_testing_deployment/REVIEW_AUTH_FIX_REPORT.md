# Module 07 review fixes — 22 October 2026

## Outcome and scope

The reviewed P1 consumer-lock defect is fixed in **07/uv.lock**: backend metadata now
includes google-auth and requests. Verification checks the committed lock and never
regenerates it. The old develop lock is archived explicitly for baseline-only checks.

All source changes are inside 07 and the already authorized root GitHub workflow.
Module 01–06 source was only read/archived into ignored disposable snapshots. No PR
was merged and no user database was migrated. This updates existing Draft PR22.

## Exact candidate, not old develop CI

[integration.json](integration.json) pins these full commits:

| Module | Revision |
| --- | --- |
| base develop | `69f534730669f59051a453d9833a0be88695f263` |
| 01 PR17 | `2b43754e1313da9afbb72bbfc4d14193fe26e083` |
| 02 PR18 | `b047e809f983ffb2e4f3f9d3e3f074b8976cd6da` |
| 03 PR19 | `c3c7c598ae2f6692d360c8cd5d8d6aacc1e6fc04` |
| 04 PR20 | `1c1c536de3d2a316cc239b8f21b186cd8169aff8` |
| 05 PR23 | `144d2b14848bec0085f2ff9d0cee6453e9ba1391` |
| 06 PR21 | `fafece3e5a24229628c8616a463a042af96b974d` |

Every CI job now assembles this manifest and copies the reviewed 07 tooling/lock.
It publishes module revisions, tooling commit/dirty state, tooling and lock SHA-256.
Mutable/incomplete manifests fail. Nothing is silently merged or fetched as a moving
branch at test time. Candidate success is not a merged-develop acceptance claim.

## Executed local verification

Windows, Python 3.11.16, uv 0.12.9, pnpm 11.25.0 and Docker Linux containers.

| Gate | Result |
| --- | --- |
| Original 07 lock against the new backend | Reproduced stale-lock failure before the fix |
| Committed fixed 07 lock --check/--offline and sync --locked | Passed |
| All consumer locks: 02 core/integration/full, 03, 04, 05, 06 core/acceptance, 07 | 9 passed, no lock regeneration |
| Upstream Python suites on the exact candidate | 590 passed: 96/107/126/114/102 + 9 integration + 36 full |
| 07 acceptance and regression | 20 + 4 passed |
| Strict auth | 11 passed, including real 03–06 domain services and new migration/restore drill |
| Total Python | **625 passed**, live provider tests excluded explicitly |
| Ruff check/format | Passed |
| Frontend typecheck/format/build/production bundle smoke | Passed |
| Frontend unit tests | 69 passed |
| General browser regression | 47 passed, 7 opt-in skips: 6 identity cases run separately below, 1 old standalone workspace/backend scenario remains skipped |
| Real HttpSessionPort/API/worker browser run | **7 passed**, no `/api` route mocks |
| Production auth factory + actual HTTPS reverse proxy | Passed on fresh isolated state/internal Docker network |

The previous 8 failures + 21 errors belong to the 21 October revisions. They are not
suppressed here: the new owner-provided 03/05/06 fixes are pinned and their suites pass.
No auth flag was disabled to repair those upstream tests. The existing 07 legacy-domain
regression still explicitly uses its test-only legacy setting, separately from strict auth.

## New browser and deployment evidence

`browser_identity.py` starts the pinned real API and worker with module 01's explicit
loopback test server. The normal frontend entry uses HttpSessionPort. Only external
GIS/Google verification and provider results are synthetic. Tests cover challenge nonce,
cookie/session restoration, returning identity, CSRF, first-user role, role/suspension
revocation, last admin, imports/chat/citations/quiz/research/events, shared detach,
logout/account switching and history isolation. The 07 research case exercises actual
HTTP job submission and worker polling. This uses HTTP loopback cookies; it does not
claim real Google or production TLS browser sign-in.

`docker_auth.py` starts the actual production/custom/live factory with secure auth
settings, fresh schema **0002**, real paired initialization, worker and the built new UI.
Its internal network blocks provider egress. HTTP runs through Caddy over local HTTPS;
checks confirm authenticated mode, all nine capabilities, pair preflight, Secure/HttpOnly/
SameSite challenge cookie, unauthenticated API 401 and SPA fallback. `/api` and unknown
API paths are proxied rather than served index.html. Image IDs are recorded and only
the drill's own project/volumes are cleaned up. Synthetic keys are never used for calls.

The drill intentionally creates **no release attestation**. It checks production factory
settings without pretending that the final public release gate/manual Google smoke passed.

## Migration and paired restore

`tests/auth/test_migration_drill.py` seeds actual fixture SQLite/Chroma, constructs legacy
schema 0001 only on that disposable copy (with zero identities), takes a checksummed
cold pair, and invokes the actual operator migration CLI with its own backup. It confirms
first sign-in remains user with no adopted library, runs explicit bootstrap and legacy
claim, checks revoked sessions/admin ownership, backs up and restores the migrated pair,
then confirms the restored owner library. A separate pre-migration restore confirms
schema 0001 and unchanged Chroma checksums. No production downgrade is suggested.

## Evidence and reproduction

Use README's pinned-candidate commands. Do not run canonical locked sync directly against
the old develop module manifests. Local artifacts are under ignored
`07/runtime/candidate-ecf31b2208/`:

- `07_testing_deployment/runtime/20261022T031928385078Z/`: complete combined upstream/07 run.
- `07_testing_deployment/runtime/consumer-lock-checks.json`: nine read-only lock checks.
- `07_testing_deployment/runtime/*/07-auth.xml`: strict auth and migration drill.
- `07_testing_deployment/runtime/browser-identity-*/`: adapter/API/worker logs and provenance.
- `runtime/screenshots/identity-*.png`: real-adapter UI with synthetic identities/providers.
- `07_testing_deployment/runtime/yk07-auth-*/`: HTTPS/container health, image IDs and cleanup.

Representative current results/provenance are committed in `evidence/review-2026-10-22/`.
CI evidence must be read from the current PR head; the old run 39625878050 is historical
baseline-only evidence, as the reviewer correctly noted.

## Remaining release gates

The user confirmed no registered Google staging origin/client ID is available. Real
Google first/returning/cancel/logout/switch stays **pending**. No attestation field was
filled true to bypass it. Public certificate/DNS/browser secure-session acceptance,
actual merged-develop rerun, and opt-in live Gemini/captions/answer-quality acceptance
remain separate. Keep PR22 Draft; do not describe these automated results as release approval.
