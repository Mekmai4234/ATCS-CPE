# Google identity and private ownership (module 02)

Authentication is enabled by default. No API key, Google Client Secret, first-user
admin promotion, email-based account linking or browser-provided role is used.
02 changes only backend files; 01 must implement this login contract and 07 must
configure Google origins/HTTPS and run real-account acceptance before deployment.

## Configuration

```dotenv
AUTH_ENABLED=true
GOOGLE_CLIENT_ID=YOUR_WEB_APPLICATION_CLIENT_ID.apps.googleusercontent.com
SESSION_TTL_SECONDS=86400
SESSION_COOKIE_SECURE=true
AUTH_TRUSTED_ORIGINS=["https://app.example.com"]
WEB_ORIGIN=https://app.example.com
```

Use the full launcher's selected server env file for the full system. Origins
must be exact, without wildcards, paths or trailing slash. In local HTTP development
only, set `SESSION_COOKIE_SECURE=false` and use an exact localhost web origin.
Use the same host name consistently; localhost and 127.0.0.1 are different hosts.
Prefer production same-origin reverse proxy for frontend and `/api`. Cross-origin
same-site development needs fetch `credentials: "include"`; CORS explicitly allows
credentials only from configured origins. Cross-site cookie deployment is not
supported by this SameSite=Lax contract.

Cookies are HttpOnly, SameSite=Lax, path `/`, with no Domain. Secure cookies use
the `__Host-` prefix. Opaque random sessions have 256 bits of entropy; only their
hashes and CSRF hashes are stored in SQLite. No persistent signing secret is needed.
Logout revokes the server session. Login rotates the browser's existing session.
Role/status updates revoke every session of the target account. Suspension also
invalidates running execution at its next fence. Expiry is checked server-side.

`AUTH_ENABLED=false` is an explicit **development/test-only** compatibility mode
for the historical single-user fixtures. It is rejected outside development/test.
Do not reuse its anonymous database for authenticated users; use a fresh pair.
Production additionally requires Secure cookies and HTTPS trusted origins. Missing
Google Client ID returns 503 for login challenge; it never opens protected APIs.

## Contract for module 01

Only `/health`, `GET /api/auth/challenge`, `POST /api/auth/google` and development
API documentation are public. API docs describe schema, not private account data.
All data routes require a live session. API responses use `Cache-Control: no-store`.

1. `GET /api/auth/challenge` with credentials included returns
   `{client_id, nonce, csrf_token}` and sets an HttpOnly login-challenge cookie.
   Challenges expire in five minutes and are single use. A maximum of 30 challenges
   per direct client IP in that window applies, including consumed challenges.
   07 should add ingress abuse controls and configure trusted proxy handling.
2. Use **Google Identity Services JavaScript callback flow**. Set the returned
   `client_id` and `nonce` in `google.accounts.id.initialize`. The site requests
   only identity/profile information, not Gmail access.
3. Send `POST /api/auth/google` JSON
   `{credential: googleResponse.credential, csrf_token: challenge.csrf_token}`
   with credentials included. Browser Origin must match the allowlist. Do not add
   user_id, role or profile properties. This is not GIS's automatic redirect/form
   POST flow; its `g_csrf_token` contract is not interchangeable with this challenge.
4. A successful login returns `{user, csrf_token}` and sets the session cookie.
   `user` contains user_id, email, name, picture, role and status. Accounts are
   identified only by verified Google `sub`; changing email keeps the same account.
   New accounts always have role `user`. Google token verification follows the
   [official server verification guidance](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token):
   google-auth verifies signature/audience/issuer/expiry, with explicit claim and
   challenge nonce checks before account/session creation. Certificate transport is
   HTTPS with a five-second request bound. Raw verification errors are not returned.
5. `GET /api/auth/me` restores `{user, csrf_token}` after page reload. Keep the CSRF
   token in memory and add `X-CSRF-Token` to every POST/DELETE (including logout).
   Never put credential/session secrets in localStorage. Browser Origin is checked
   on all mutations in addition to the session-bound CSRF token.
6. `POST /api/auth/logout` revokes the current session and deletes its cookie.

Error shape remains `{error: {code, message, retryable, request_id}}`. Common statuses:
401 authentication_required/invalid_google_token; 403 csrf_invalid/admin_required/
account_suspended; 404 not_found/video_not_found; 409 last_admin/shared_import_required;
429 login_rate_limit; 503 auth_not_configured. Invalid body/extra role fields get 422.
Unauthenticated requests fail before body processing or adapter/provider invocation.

## Ownership and shared source contract (03–06)

- Central videos/transcripts/vectors are shared. `user_videos` grants library access.
  Knowing a video ID grants no transcript/search/scope access. Explicit import of a
  supported URL creates a membership; unclaimed legacy/unowned sources are rejected.
- Each subscriber receives a private import job ID. A queued `attach` job waits for
  shared ingestion; a ready shared source attaches without reindexing. Failed attach
  can be retried. No response returns the original subscriber's job ID.
- Cancellation/retry/status/events/history/artifacts are checked against the actual
  authenticated owner. Idempotency keys are hashed with account and operation identity;
  the same key in two accounts cannot collide. Historical conversation contents remain
  private to their owner; removed-source citations are marked unavailable.
- Delete removes only the caller's library membership. If others remain, a completed
  `detach` job records that removal; their transcripts/vectors/jobs are untouched.
  A shared physical import cannot be cancelled while another subscriber needs it;
  the owner may detach instead. Ingestion can finish for remaining subscribers.
- Last-member deletion marks the source deleting under BEGIN IMMEDIATE, cancels the
  departing user's affected work and creates durable physical GC. New imports cannot
  attach while deleting. GC waits for running/queued source readers and rechecks zero
  memberships at lease/publication fences. No vectors are deleted in an HTTP request.
  Suspended accounts retain memberships until explicitly removed; this is conservative
  retention, not permission for them to read while suspended.
- New jobs/conversations/artifacts have server-assigned owner IDs. Related messages,
  citations and events inherit permission through their parent. Admin is not an
  ownership bypass. No account-wide cache is introduced.
- `ExecutionContext.user_id` comes from the durable, leased job, not request JSON.
  `check()` revalidates active owner, current membership, source version and lease.
  `authorize_sources(sources)` additionally verifies the frozen source set for AI work.
  Existing 04 BackendExecution already invokes these lease checks; its transaction
  fence invokes Repository._owned and therefore enforces account/source revocation
  atomically at publication. 03–06 must keep checking context before effects and must
  never broaden frozen scope or replace the context with user input.

## Administration

An active admin may call `GET /api/admin/users?q=...&limit=...&offset=...`,
`POST /api/admin/users/{user_id}` with `{role?, status?}`, and `GET /api/admin/stats`.
Statuses are active/suspended; roles are user/admin. Mutations require CSRF. The last
active administrator cannot be demoted or suspended. Identity changes are audited with
actor, target, before/after state and timestamp. Statistics expose counts by state,
never job prompts, results or conversation contents. Admin cannot read another user's
data routes or claim legacy content through an HTTP API.

First login creates an ordinary user. After verifying the intended account's Google
sub in the `users` table on the trusted server, an operator explicitly runs:

```powershell
uv run --project 02_api_backend/full --locked yk-full bootstrap-admin --google-sub VERIFIED_SUB
```

This works only when there is no active admin, revokes that user's sessions, and is
audited as an explicit operator action. Log in again to receive a fresh session.
For a lightweight backend, `yk-auth bootstrap-admin` uses its configured Settings.

## Legacy migration and rollback

Stop API **and** workers, including other hosts sharing the store. The operator's
`--workers-stopped` assertion is required; it is not an inter-process stop mechanism.
On a fresh pair, `yk-full init` creates revision **0002** directly. For existing 0001:

```powershell
uv run --project 02_api_backend/full --locked yk-full migrate --workers-stopped --backup-dir C:/backups/yk-before-auth
```

The full launcher exports the same selected settings to operator commands, so they
cannot silently read a different root/module dotenv. `yk-auth migrate` is the direct
lightweight equivalent. Ordinary `yk-db upgrade head` and initializer functions refuse
an unbacked upgrade from 0001.

Migration first writes a consistent SQLite backup and copies the stopped Chroma tree
to a **new** backup directory outside Chroma, with source paths in backup.json.
Committed deletions must finish under the old release before stopping/migrating;
sources still marked deleting are refused before backup or schema changes. Known
02/04 pair markers are checked before copying; existing RAG runs with a missing index
are refused. Protect this directory: it contains private data and any existing sessions.
Migration retains SQLite/Chroma pairing and source records. Existing owners remain
NULL and source IDs are recorded in `legacy_sources`; old queued/running work is
quarantined as cancelled/legacy_owner_required, never automatically replayed.

Sign in the intended owner and administrator through verified Google login first.
An operator then approves the one-time assignment explicitly:

```powershell
uv run --project 02_api_backend/full --locked yk-full claim-legacy --admin-sub VERIFIED_ADMIN_SUB --owner-sub VERIFIED_OWNER_SUB
```

This assigns only unowned records and quarantined source memberships, records the
approval, and removes those quarantine markers. It does not infer identity from an
email or grant existing private libraries to the administrator. Interrupted legacy
research is not replayed; import/analysis can be resubmitted explicitly after review.

For rollback, stop all processes and restore **both** app.db and Chroma from the same
backup into the recorded configured locations; retain old copies for inspection.
Do not restore only one store. Use the pre-migration application version to open a
0001 backup. Populated identity databases cannot be downgraded automatically because
that would discard permissions/sessions; restore the backup instead. Empty-schema
downgrade exists only for migration verification. Never delete data to pass migration.

## Verification and handoff

See AUTH_TEST_REPORT.md for observed checks and limits. Real Google-account browser
login is still an acceptance step requiring the team's actual OAuth Web Client ID and
authorized origins. 01 must implement the nonce/challenge flow, credentialed fetch,
session-aware redirects and CSRF headers. 07 must configure HTTPS/origins, migration
backup/restore, update root deployment instructions and exercise two real accounts.
03/04/05/06 should consume the trusted execution contract, not user_id from payloads.
