# Native member ingestion handoff — 02 / 03 / 04

Updated 2026-10-22 after review of 00_summary.md, 03_review_and_fixes.md,
08_verification.md and 09_system_progress.md. This replaces the earlier proposal.
There is one runtime flow; no repository.member_ingestion_backend, SourceGrant,
MemberIngestion or second membership store is required.

## Dependency candidate

- Base develop: 69f534730669f59051a453d9833a0be88695f263.
- 02: PR18, origin/codex/02-google-auth-ownership at b047e80 (current reviewed handoff;
  later than the review snapshot f406d32).
- 04: PR20, origin/codex/04-authorized-rag-sources at d4aa52d.
- 03: this branch; only module 03 files changed in this PR.

02/04 are not merged here. Verification uses a disposable archive candidate with these
exact source trees and the current 03 tree. Do not expect the new 03 lock or member
suite to work against the single-user develop dependency trees. This is a dependent
integration PR, not a self-contained release on old develop.

## Native runtime path

1. 02 authenticates HTTP through challenge/Google exchange, server-owned session,
   Origin and CSRF checks. Never use client user_id/owner_id/role as authority.
2. POST /api/videos/import calls Repository.import_urls. The transaction validates URLs,
   assigns user_videos and returns the requester's private import/attach job ID. A
   second member joins existing work; a ready source completes attach without caption
   or vector requests. Status/outcome DTOs are 02's public schemas, not new 03 schemas.
3. 02 Worker claims the durable job and supplies ExecutionContext to 03 IngestionService.
   The service checks it while fetching, observes deadlines and retains bounded child
   cleanup. The native repository rechecks owner/status, source references and lease.
4. 02 persists the TranscriptResult/version, then calls 04 RagAdapters. BackendExecution
   uses the same repository's transaction-level _owned fence for index publication and
   deletion; 04 checks generation, references and active readers at its storage boundary.
5. GET job/transcript, retry and cancel stay behind 02's session/ownership middleware.
   Admin does not bypass private jobs/library access. Read/search consumers use 04's
   authorized context. 03 does not add routes or an alternate DTO/session layer.
6. DELETE /api/videos/id detaches only the caller. With other references it returns a
   completed detach job; with zero references it creates a durable delete job. GC waits
   for active dependencies. Shared import cancel returns shared_import_required (409);
   detach is the native supported way to withdraw without breaking other members.

The existing integration:create_adapters implements ingestion/RAG composition.
member_adapters:create_member_adapters retains the old configuration name as a guard
for native authenticated 02, then calls that same factory. It checks auth_enabled,
users/user_videos, authorize_sources, 04 permission_scope and repository authorization support before
constructing provider clients. These shape checks are compatibility checks, not proof
of correct authorization; real integration tests supply that evidence.

## Limits and ownership

02 owns Google verification, sessions/CSRF, account state, private jobs, membership
transactions, import batch admission, migrations and legacy-data ownership. 04 owns
transactional publication, authorized reads and physical GC. 03 owns provider fetch,
normalization, classified failures and bounded subprocess cleanup.

02 IMPORT_MAX_URLS is enforced at native admission and tested through HTTP. The removed
MEMBER_PENDING_IMPORT_LIMIT/MEMBER_RUNNING_IMPORT_LIMIT settings never implemented
quotas. Durable per-member pending/running limits and fair claim scheduling are not
implemented by 03 and are not claimed as complete in this dependency candidate.
Those remain upstream release requirements. No user/migration/auth data is changed by
03 and no global fixture disables production authentication.

## Tests and release gates

- Legacy lifecycle tests set auth_enabled=False on that fixture only, preserving old
  pipeline/delete/cancel regressions with explicit test/development behavior.
- test_native_members.py enables auth, logs in two principals through challenge and
  Google exchange, sends cookies/CSRF and uses real HTTP/SQLite/worker/Chroma. Only
  external Google, captions/metadata and vector values are doubles.
- acceptance_check.py explicitly requires --fixture-identity --fixture-embeddings and
  a new empty state directory. Its verifier exists only inside that isolated test app;
  the report labels fixture identity and does not claim real Google/browser login.
- 03 uv.lock is refreshed against the dependency candidate. Run uv lock --check --offline,
  uv sync --locked and pytest -q -W error there. Do not regenerate against old develop
  and hide the dependency mismatch.
- 03 Dockerfile consumes this same lock with --locked, packages the three modules and
  defaults to native authentication. Its Dockerfile-specific allowlist excludes .env,
  databases and unrelated files. Actual Docker build/run remains unverified locally.

Before production: merge/coordinate dependency and consumer locks, verify durable
quotas/fair claims, browser-to-backend real Google login, all 05/06 read scopes,
production container behavior and migration/restore. No PR is merged by this work.
