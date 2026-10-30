# Floating chat backend verification — 2026-10-24 (Asia/Bangkok)

Base: `develop@8967c6060e795fea153ff598a33536fd722d43a4`.
Implementation/browser backend ref: `79f83d0d0ca4098b7c6ee31ab9d42adeb04e8382`.
All tracked edits are in 02. Existing dotenv, application databases and indexes
were untouched; each test uses a new temporary store. Documentation commits after
the implementation ref do not change the application or test code.

## Proven gap and fix

Before the fix, the new HTTP contract suite had **5 failures, 3 passes**: anonymous,
expired, logged-out and suspended-session 401 responses, and mutation-CSRF 403,
lacked `Access-Control-Allow-Origin` for the configured trusted frontend. The auth
middleware generated these responses outside CORS. The existing no-store policy
was already present and is retained.

CORS is now registered outside authentication middleware, using the same exact
origin allowlist, credential/header policy and CSRF checks. Trusted frontends can
read session errors and clear private UI; unknown origins receive no approval.
OpenAPI now documents the existing 401/403/429 error response schemas too.
No session system, endpoint, schema migration or configuration variable was added.

## Final observed checks

| Check | Result |
|---|---|
| Final Windows core + integration + full, warnings as errors | **151 passed**, 126.64s |
| Rebuilt Linux full Docker, networking disabled | **151 passed**, 149.82s |
| Targeted floating-chat HTTP/schema suite | **10 passed**, 2.26s |
| Pinned 01 real adapter/browser identity suite, same-origin development proxy | **6 passed**, 33.2s |
| Same pinned browser suite, direct cross-origin API (`VITE_API_SAME_ORIGIN=false`) | **6 passed**, 35.8s |
| Ruff check/format, all 55 module-02 Python files | Passed |
| Three 02 uv locks, offline check | Passed |

The HTTP contract tests cover 200 and deterministic pending 202, Location/polling,
deduplication and key conflicts, conversation busy, shared widget/page cookie state,
pagination, guessed private IDs even after shared import, scope-filtered provider
history, source removal/availability, no-evidence versus invalid/unready/removed
scope, secret/message logging and published JSON examples against real schemas.
The 202 test deliberately holds execution in a named test double; it does not claim
that an actual paid provider was slow. The full factory additionally verifies a
follow-up and history pagination through the real 05 service with account isolation.

## Browser boundary and evidence

Frontend source is exported from PR #17 at
`2b43754e1313da9afbb72bbfc4d14193fe26e083` into ignored
`02_api_backend/runtime/web-chat-20261024/`. Its existing `tests/identity_smoke.py`
exports the pinned backend, starts a real auth-enabled HTTP server/worker and runs
the actual `HttpSessionPort`/API adapter in Chrome without browser API mocks.
Only Google GIS/verifier and provider data are explicitly synthetic. The snapshot
reuses installed Node dependencies via a local node_modules junction; this is the
selected identity suite, not a fresh dependency install or all of PR #17's CI.

Both modes exercise nonce/relogin/cookies, private chat/account switching, shared
source detach, citation state and admin/CSRF/revocation. They establish that the
current adapter can read auth failures with the corrected backend. They do not
certify new draggable-widget UI, mascot behavior, real Google accounts, production
HTTPS cookie behavior or live model quality. The two-surface shared-conversation
case is independently tested through HTTP clients sharing the browser session.

Same-origin evidence: `identity-check-572446bbd9`; direct-origin evidence:
`identity-check-ba89c9e61b`, beneath that snapshot's `MiniProject/01_web_app/runtime/`.
Each report records auth_enabled=true, backend ref, verifier fixture and no paid
provider calls. API/worker/Vite processes are stopped by the runner.

The full Docker project is `yk02-check-0cf478139f`. Its report/log remain in ignored
`runtime/yk02-check-0cf478139f/`. The smoke verifies real-factory non-root API/worker,
pair/schema/configuration checks and anonymous rejection across recreation. The
test suite uses real 03 normalization/04 Chroma/05 services/06 controller, while
Google/captions/metadata/embedding/generation transports are labelled doubles.
Its generated containers, network and data volume were removed successfully;
test images and reports remain locally. Existing unrelated Docker resources were untouched.

## Reproduce

From MiniProject:

```powershell
uv run --project 02_api_backend --locked pytest 02_api_backend/tests/test_chat_contract.py -q -W error
uv run --project 02_api_backend/full --locked pytest 02_api_backend/tests 02_api_backend/integration/tests 02_api_backend/full/tests -q -W error
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_full_smoke.py
```

For the browser check, export the pinned 01 directory with `git archive` into a new
ignored directory under 02 runtime, provide that copy's Node dependencies, and run
its existing `tests/identity_smoke.py --ref 79f83d0` with module-02's Python environment.
Run once with the default same-origin proxy and once with the process environment
`VITE_API_SAME_ORIGIN=false`. No checkout/merge or tracked 01 change is necessary.
Do not run against real application stores; the runner creates its own temporary
backend copy/database. Use FLOATING_CHAT_CONTRACT.md to implement the widget's
shared state and session-revision guard before claiming its UI acceptance complete.

No real Google login, real YouTube/Gemini request, staging deployment or live-data
migration was performed. Those remain explicit team acceptance, not hidden passes.
