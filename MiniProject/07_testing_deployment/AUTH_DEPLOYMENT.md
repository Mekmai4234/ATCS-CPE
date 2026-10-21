# Auth deployment and legacy recovery

**Current status: blocked for public auth deployment.** Develop lacks identity; the
candidate UI's PendingSessionPort deliberately blocks the private workspace. Do not
substitute demo mode, disable authentication, or treat a manually edited evidence JSON
as proof of integration. `auth_readiness.py` validates configuration and an operator's
attestation; it does not independently verify claims inside that attestation.

## Public origin and credentials

Use one registered HTTPS origin for UI and `/api`. `Dockerfile.web` builds module 01
with only `PUBLIC_ORIGIN` and public `GOOGLE_CLIENT_ID`; the backend key remains a server
environment value. Caddy terminates TLS and proxies `/api/*` and `/health` to API.
The overlay removes the host API publication. Set DNS and permit public ports 80/443
before public certificate issuance; local smoke uses a disposable Caddy local CA.

Register the exact scheme/host (and port for localhost) in Google Authorized JavaScript
origins. See [Google GIS setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid).
Backend requires `AUTH_ENABLED=true`, `SESSION_COOKIE_SECURE=true`, matching `WEB_ORIGIN`
and `AUTH_TRUSTED_ORIGINS`, and the same Google client ID used by the frontend adapter.
Do not put cookies, session credentials, Google tokens, OAuth secrets or Gemini keys in
build arguments, committed env files, screenshots or CI output.

## Release gates and commands

First merge and rerun all 01–06 changes on actual develop. Require zero regression
failures, the strict auth suite, domain-service ownership tests, production bundle
isolation, real browser/backend flow and manual Google staging smoke. Record exact
revision/image digest, date and reviewer. Evidence mounted as `/evidence/release.json`
must contain:

```json
{
  "revision": "EXACT_TESTED_COMMIT",
  "image_digest": "EXACT_TESTED_IMAGE_DIGEST",
  "google_login": false,
  "logout_account_switch": false,
  "browser_backend_flow": false,
  "ownership_suites": false,
  "reviewed_by": "",
  "tested_at_utc": ""
}
```

This deliberately failing example must never be changed to true without the respective
evidence. `scripts/auth_readiness.py --env-file PATH --evidence PATH` exits nonzero until
all checks pass. The auth compose overlay makes preflight run this check **before**
initialization and on both API/worker startup, without printing configuration values.

After acceptance, set `PUBLIC_HOST`, public `GOOGLE_CLIENT_ID`, server `GEMINI_API_KEY`
and absolute `AUTH_EVIDENCE_DIR` in a secure shell. Build/run from MiniProject:

```powershell
docker compose -f 07_testing_deployment/compose.yaml -f 07_testing_deployment/compose.auth.yaml build
docker compose -f 07_testing_deployment/compose.yaml -f 07_testing_deployment/compose.auth.yaml up -d api worker web
```

These are prospective commands, not evidence that the auth stack currently works.
`compose.yaml` alone is the older localhost development stack. Never expose that stack
as a multi-user production service. Compose auth requires modern Compose supporting
`!reset` and rejects missing host/client ID/evidence directory.

Local packaging checks (no real sign-in or provider usage):

```powershell
docker build -f 07_testing_deployment/Dockerfile.web -t youtube-knowledge-team07-web:auth-check .
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/web_smoke.py
docker compose -f 07_testing_deployment/compose.yaml build api
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/docker_startup.py
```

The web drill verifies actual container TLS, headers and SPA fallback, disables host
proxy inheritance and trusts only the disposable container certificate for that request.
It does not install that CA, validate public TLS, authenticate or verify backend proxy
traffic. Both drills clean only their randomly named containers/volumes.

## Legacy migration and first admin (module 02 PR 18 contract)

1. Stop API and every worker/maintenance writer. Finish committed deletions first.
   Keep the old image/schema/embedding fingerprint and take a paired cold backup per
   [RECOVERY.md](RECOVERY.md); verify checksums and restore into a new disposable path.
2. With the **new auth implementation** installed and the same selected full config,
   run `yk-full migrate --workers-stopped --backup-dir NEW_BACKUP_DIRECTORY`.
   The migration must create the SQLite/Chroma backup before schema 0002; never use
   ordinary fresh initialization to adopt a populated legacy database.
3. Legacy content stays quarantined without an owner. First sign-in is always `user`.
   Verify a team member's Google `sub` using the trusted server identity, then explicitly
   run `yk-full bootstrap-admin --google-sub VERIFIED_SUB`. Existing sessions are revoked;
   sign in again. Never infer admin from first login, email or a browser-supplied role.
4. If legacy adoption is approved, separately run
   `yk-full claim-legacy --admin-sub VERIFIED_ADMIN_SUB --owner-sub VERIFIED_OWNER_SUB`.
   Inspect A/B isolation and legacy conversations on the restored copy before live use.
5. Confirm schema, pair binding, index fingerprint, cookie flags and health capabilities
   without revealing secrets. Run fixture suites against copies, then manual Google
   selection/cancel/relogin/logout/account-switch and the complete private workspace flow.
6. For rollback stop all writers and restore **both** pre-migration stores to a new
   destination with the matching old code/config. Do not downgrade a populated identity
   database or mix a migrated SQLite file with an unrelated Chroma directory.

Use `yk-full --help` from the actual deployed 02 revision to confirm migration/admin
commands before execution; develop without PR 18 does not provide them. No migration,
bootstrap, legacy claim, live Google sign-in or public deployment was performed here.
