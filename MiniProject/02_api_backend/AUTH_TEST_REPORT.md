# Google identity / ownership verification — 2026-10-21 (Asia/Bangkok)

Base: `develop@69f5347`. Changes are restricted to `02_api_backend` on
`codex/02-google-auth-ownership`. Existing user dotenv files, application databases,
indexes and other modules' tracked files were not edited. Verification uses new
temporary stores or explicitly created test containers; no live credentials.

## Delivered

- Server-verified Google ID tokens, a nonce-bound single-use login challenge and
  login/API CSRF enforcement. New members are users; verified Google sub is unique.
- Hashed random server sessions, hardened cookies, expiry/logout/revocation,
  role/status administration with audit and last-active-admin protection.
- Revision 0002 adds identity, sessions, challenge, membership, audit, quarantine
  and nullable legacy owner columns. Startup/health/initializers require 0002.
- Request ownership across all data routes, account-scoped idempotency, trusted
  worker identity/frozen sources and transactional publication/GC authorization.
- Shared source imports use private subscriber job IDs. Detach preserves other
  libraries; physical GC waits for readers and rechecks no remaining membership.
- Explicit administrator bootstrap and approved legacy claim, paired backup before
  legacy upgrade and recovery documentation. Full launcher operator commands keep
  the same selected configuration and serialize JSON-origin settings correctly.
- Auth contract, example settings and frontend/04/deployment handoff in AUTH.md.

## Observed final checks

| Check | Result |
|---|---|
| Windows backend + integration + full suites, warnings as errors | **137 passed**, 101.86s |
| Linux full Docker same suites, networking disabled | **137 passed**, 112.48s |
| Final identity/configuration-redaction regression, Windows / Linux Docker | **28 passed** each, 7.42s / 8.54s |
| Standalone lightweight backend environment, warnings as errors | **96 passed**, 24.91s |
| Existing 03 suite with explicit legacy test mode | **78 passed**, 40.33s |
| Existing 05 suite with explicit legacy test mode | **100 passed**, 51.75s |
| Existing 06 suite with explicit legacy test mode | **75 passed**, 32.92s |
| Original 04 suite with legacy-mode environment | **82 passed, 15 failed, 1 skipped**; fixture issue below |
| Isolated 04 test copy with explicit legacy Settings fixture | **97 passed, 1 skipped**, 119.06s |
| Ruff lint/format, all 02 Python files | Passed |
| All three 02 locks checked offline; full Compose config | Passed |

The live embedding opt-in test remains intentionally skipped. The 03–06 runs use
`AUTH_ENABLED=false APP_ENV=test` explicitly to preserve their original single-user
mechanism scope; they are not authentication acceptance. No tests were silently
skipped to hide an ownership failure.

The final startup-error redaction assertion was rerun after the broad suites on
both Windows and Linux. The Docker targeted run mounted the final config.py and
test_identity.py read-only into the already-built test image. It verifies that
invalid production settings do not print a provider secret in validation errors.

### Module-04 fixture integration dependency

`04/tests/test_maintenance_store.py::isolated_environment` deletes every Settings
environment field, including AUTH_ENABLED. Its old `env` fixture then constructs a
backend Settings with the new secure default and no principal, causing 15 setup/
execution failures at import (401 authentication_required). This is a real test
compatibility issue for the combined CI; it has **not** been fixed in tracked 04 files.

To isolate RAG behavior, copied only 04's tests into ignored
`02_api_backend/runtime/rag-legacy-tests-20261021`, added **auth_enabled=False only
to that copy's backend Settings fixture**, and ran with 04's original pytest config.
The source libraries and assertions were unchanged: 97 passed, 1 live skip. This
does not mean the original suite passes unmodified. 04 must explicitly migrate its
single-user test fixture (or create authenticated principals) before combined CI
is green. The new 02 full suite independently tests authenticated real-RAG access.

## What the new tests establish

- google-auth verifies an RSA-signed token with a generated test key and mocked
  Google certificate transport. Tampered signatures, wrong audience/issuer and
  expired tokens fail; no network requests occur. Endpoint tests reject invalid
  nonce/CSRF, malformed provider verification and client-provided role fields.
- Google sub reuse keeps the same account when email changes, without promoting
  first login. Re-login rotates/revokes the browser's old session. Stored tokens
  are hashes. Logout, expiry, suspension and role changes invalidate sessions.
- Origin/CSRF mutations fail closed, challenges are single-use and retained for
  per-IP rate accounting, cookies use HttpOnly/SameSite and Secure host-prefix
  policy for HTTPS production. Production authentication opt-out is rejected.
- A cannot read B's jobs, cancel/retry, research/events, conversations or artifacts.
  Unknown and foreign resources return 404. Same idempotency key in two accounts
  produces different jobs. Admin can manage members/counts but cannot read their
  private job contents; the last active admin cannot be removed.
- Shared pending imports have distinct private jobs; detaching the first subscriber
  still lets the second finish. Retry never returns a different subscriber's
  physical job. Remaining library members retain transcript/index access.
- Last-member GC waits while a source reader is running. Revoked source/owner is
  checked at execution fences, and client-chosen sources outside the frozen scope
  are rejected. Historical citation availability follows current membership.
- Two authenticated accounts use actual 03 normalization, 04 Chroma/manifest and
  05 service through the real full factory. Unauthorized scope/transcript/history
  is denied; shared access and final vector deletion are verified. External
  captions, metadata, embedding and generation are labelled test doubles.
- Fresh upgrade/repeatability/model consistency and empty-schema rollback pass.
  Upgrade from a populated 0001 copy preserves data and real Chroma pair markers/
  vectors; unowned queued work is quarantined without replay. Legacy content and
  unowned development sources cannot be implicitly adopted by a first user.
  Explicit bootstrap/claim is required. The original SQLite/Chroma pair remains
  accessible in its pre-migration backup; real application stores were untouched.
  Migration preflight additionally refuses outstanding committed deletions before
  creating a backup; the old release must finish those before schema upgrade.

## Docker smoke

Final generated project: `yk02-check-194c86ce6f`. Its test image ran
137 tests without networking. Runtime uses a separate internal network, invalid
Gemini test key and non-root API/worker containers. Fresh schema init, shared pair
verification, all configured capabilities and wrong-directory rejection passed.
Anonymous video/chat access returns 401 before and after recreating containers.
Health reports authentication required and schema revision 0002. No Google/Gemini/
YouTube provider requests are made. Full login/cancel/data isolation runs in the
suite rather than introducing a fake identity switch into the runtime image.

Containers/network/volume from this generated project are cleaned by the script;
logs and report are under ignored `runtime/yk02-check-194c86ce6f/`.

## Reproduce

From MiniProject:

```powershell
uv sync --project 02_api_backend --locked
uv sync --project 02_api_backend/full --locked
uv run --project 02_api_backend/full --locked pytest 02_api_backend/tests 02_api_backend/integration/tests 02_api_backend/full/tests -q -W error
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_full_smoke.py
uv run --project 02_api_backend --locked ruff check 02_api_backend
uv run --project 02_api_backend --locked ruff format --check 02_api_backend
```

Historical coordinator tests explicitly opt out of auth only in their fixture
configuration. New identity tests explicitly enable it. Real Google browser sign-in
needs the team's actual OAuth Web Client ID and authorized origins; it was not
performed. No staging deployment, production load test or existing-data migration
was performed. Do not deploy until 01's login/CSRF integration and 07's HTTPS,
configuration and real-account acceptance are complete. The 04 fixture dependency
above must be addressed before claiming combined CI passes.
