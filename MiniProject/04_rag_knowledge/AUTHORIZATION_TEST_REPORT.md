# Module 04 account authorization verification

For the 2026-10-22 consumer lock fix and actual locked installation/container
validation against backend `b047e809`, see
[LOCK_HANDOFF_TEST_REPORT.md](LOCK_HANDOFF_TEST_REPORT.md). The source-overlay
results below are historical and do not establish consumer-lock validity.

Verified on 2026-10-21 (Asia/Bangkok). The implementation and all tracked changes
are confined to `MiniProject/04_rag_knowledge`. The base checkout is
`develop@69f5347`. Authenticated integration uses the unchanged 02 PR #18 source
snapshot `f406d326a8545d1f2468a7ea3c074c5144a80a9b`, exported only into ignored 04
runtime storage. That snapshot is a test dependency, not source included in this PR.

## Results

| Check | Observed result |
|---|---|
| Full 04 suite with pinned account-aware 02, Windows | **126 passed, 1 skipped**, 194.22 seconds |
| Same account-aware suite, Docker Linux, networking disabled | **126 passed, 1 skipped**, 197.18 seconds |
| Legacy backend compatibility suite, Windows | **109 passed, 2 skipped**, 123.59 seconds |
| Same legacy backend compatibility suite, Docker Linux | **109 passed, 2 skipped**, 131.89 seconds |
| Separate Docker seed/reopen containers, persistent volume | Passed; 2 fixture videos, 7 chunks, 8/8 reference questions within top 3, scope preserved |
| Earlier failed native-process cases rerun in isolation | **12 passed**, 22.23 seconds |
| Ruff lint/format on host and Docker | Passed, 28 Python files |
| Host source vs tested Docker image | All 28 Python files have identical SHA-256 hashes |
| `uv lock --check` / whitespace check | Passed; no dependency or lock changes |
| Change-scope and credential-pattern scan | 17 tracked candidate files, all inside 04; no credential-pattern matches |

The account-aware suite includes 17 authenticated cases and all legacy assertions
under explicit legacy fixture settings. Its single skip is the live Gemini opt-in.
The pre-auth backend suite additionally skips the account test module because the
contract does not exist there; that pass alone does not establish account isolation.

## Coverage

- Real 02 identity schema/repository/leases and actual file-backed SQLite/Chroma;
  active test principals A/B/admin are server-seeded, not supplied by a prompt.
- Cross-account and empty-scope rejection before provider/vector access across
  search, inventory, chunk pages and evidence. Foreign chunk IDs reveal no evidence.
- Channel/date intersection within the caller's explicit permitted video IDs;
  administrator role alone grants no access to A's private source.
- Cross-account/job/grant cursor rejection; HMAC signature/offset tampering and
  old unsigned cursors are refused. Snapshot identity includes grants and frozen scope.
- Revocation during each read route prevents results from being returned while
  another subscriber retains access. Grant changes during query invalidate results.
- Payload user/owner/role claims cannot replace the durable execution owner.
- Candidate run/video/generation/version/timestamp/vector-ID corruption and invalid
  distances fail rather than becoming evidence; inventory verifies exact IDs.
- A detaches while B retains a shared source; B can still read. An in-flight import
  can finish/index/verify counts for remaining subscribers without granting detached
  A text access through the import context.
- Ordinary query jobs cannot invoke central reindex/cleanup/delete. Operator GC
  refuses deleting runs with memberships. Last-member physical GC waits for active
  readers; reimport during the deleting lifecycle is rejected. A reference introduced
  after a delete claim causes refusal before vectors/manifest change.
- Existing tests retain source versions, timestamps, scope/cursor behavior, lease
  fencing, cancellation, pairing, explicit reindex, cleanup retries and stopped restore.

## Migration and dependencies

Use 02's account/session/ownership migration first, then stopped `yk-rag init` with
the same selected runtime settings. This adds `rag04_security` and a persistent
private cursor-signing key. Manifest v1, chunks v2, embedding fingerprints and
stored vector metadata are unchanged; no bulk re-embedding is required. Old unsigned
cursors intentionally expire. Existing pair guards and backup rules remain in force.
See [AUTHORIZATION.md](AUTHORIZATION.md) for the 02/04/05/06 contract and rollback.

02 PR #18 is a merge/deployment dependency. Before that contract exists, production
or normal pre-auth development execution fails closed; legacy behavior is restricted
to historical test fixtures. With account-aware 02, auth opt-out is explicit and
development/test-only. Do not expose a partial multi-account deployment.

## Isolation and limits

No Google browser login, live YouTube read, paid Gemini request, production migration
or deployment was performed. External model behavior is a labelled hash fixture;
these checks establish authorization mechanics, not semantic retrieval quality.
The one live Gemini test is skipped intentionally.

Operator `--workers-stopped` remains an assertion. Safe asynchronous physical GC
depends on 02 atomically marking `deleting` and refusing new readers/imports until
deletion completes. 04 does not claim a distributed SQLite/Chroma transaction.
Future evidence caches and saved-citation APIs in other modules must reauthorize
through this contract; no cache or login implementation is added here.

Existing application data, user dotenv files and other module source are untouched.
Docker uses networking disabled, empty Gemini credentials, non-root test containers
and a read-only mount of the pinned backend dependency. Test databases are temporary.

An earlier concurrent run had native Chroma subprocess failures and interrupted
Docker output. It was not counted as successful validation; isolated/sequential
reruns determine the final results. No failing case was skipped to obtain a pass.

## Reproduction

From `MiniProject/04_rag_knowledge`:

```powershell
uv run --locked python scripts/check_account_contract.py --backend-ref f406d326a8545d1f2468a7ea3c074c5144a80a9b
docker compose -f compose.test.yaml -p yk04-authorized build tests persistence
uv run --locked python scripts/check_account_contract.py --backend-ref f406d326a8545d1f2468a7ea3c074c5144a80a9b --docker-image yk04-authorized-tests
uv run --locked pytest tests -q -W error
docker compose -f compose.test.yaml -p yk04-authorized run --rm --no-deps tests pytest tests -q -W error -o cache_dir=/tmp/pytest-cache
```

Without the account-aware backend, the account-test module reports one explicit
dependency skip in addition to the live test skip. The pinned integration commands
must run those account cases; a legacy-only pass is not multi-account acceptance.

Ignored evidence includes `runtime/authorized-host-final.log`,
`runtime/account-contract/f406d326a8545d1f2468a7ea3c074c5144a80a9b/tests.xml`,
`runtime/authorized-docker-rerun.log`, legacy host/container logs and
`runtime/authorized-audit.json`. The audit records code hashes, changed-file scope
and credential-pattern scan results; it contains no account/session/provider secrets.
Final compatibility logs are `runtime/authorized-legacy-rerun.log` and
`runtime/authorized-docker-legacy-rerun.log`; persistence evidence is in
`runtime/authorized-persistence-seed.log` and `runtime/authorized-persistence-verify.log`.
