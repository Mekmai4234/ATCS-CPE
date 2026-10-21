# Account-aware RAG contract (04)

Contract version: 1. This module consumes the account-aware backend contract in
02 PR #18, tested at `f406d326a8545d1f2468a7ea3c074c5144a80a9b`. Merge/deploy the
02 ownership/session migration before enabling this 04 release for members. This
PR contains only 04 files; it does not implement Google login or backend ownership.

## Trusted boundary

Use `BackendExecution(context)` with an actual server-created 02 `ExecutionContext`.
The durable leased job supplies `owner_id`, kind and frozen `payload.sources`.
`context.check()` / `repository.check_execution()` must revalidate account status,
current memberships, source generation/version, cancellation and lease. The
backend's `authorize_sources()` verifies the frozen AI scope. Prompt/browser
`user_id`, `owner_id`, role, video IDs or context-shaped JSON confer no authority.

Authenticated 02 must expose `users`, `user_videos` and the source lifecycle tables
in the same SQLite database as the 04 manifest. Read access requires an active
durable owner and current library membership for every requested source. Admin is
subject to the same membership check. Grant creation time and account update time
participate in a permission snapshot alongside actor, job and frozen sources.

02 resolves channel/date/library filters into explicit permitted `Source` objects
before invoking 04. 04 never expands filters, accepts an empty source set as a
global search, or authorizes a source from a chunk ID. Current 02 `Scope` requires
nonempty video IDs; a future all-library operation must resolve the caller's own
memberships in 02 first. Channel/date filters are intersections, not grants.

## Reading and revocation

| Method | Required behavior |
|---|---|
| `search` | Authorize first; filter Chroma by published permitted run IDs before ranking; verify each candidate's vector ID, run/source/version/timestamps and embedding fingerprint against SQLite; recheck permissions before returning. |
| `inventory` | Verify exact vector IDs, not just counts, within authorized runs; recheck permissions before returning counts. |
| `read_video_chunks` | Authorize pagination and coverage metadata; verify signed account/job/scope cursor; recheck before returning pages. |
| `evidence` | Resolve chunk IDs only inside authorized runs and recheck before returning evidence used for citations. Unknown or foreign IDs yield no evidence and reveal no cross-library existence. |

Permission denial/cancellation/source changes propagate as errors. 05/06 must stop
or handle them explicitly according to their partial-result contract; they must
not turn them into an ordinary no-evidence answer. 02 still owns HTTP citation and
history authorization. There is no separate public citation resolver in 04: use
`evidence` with the live trusted context, including for previously saved citations.

Pagination uses HMAC-SHA256 over versioned cursor state. The snapshot includes
account, durable job, grant revisions, selected source versions and active run IDs.
Replays across accounts/jobs, changed grants, changed indexes, modified offsets,
invalid signatures and unsigned old cursors return `invalid_cursor`. Restart from
the first page. No evidence cache is introduced. Future caches in 05/06 must bind
these same identities and reauthorize cache hits; a cursor/cache key is never a
permission grant.

## Shared storage and physical deletion

Keep videos/transcripts/vectors shared; ownership stays in 02's `user_videos`.
Detaching A invalidates A's execution without removing B's shared vectors.
Authenticated import workers may finish for remaining active subscribers after
their creator detaches. Their `inventory` call is a narrowly scoped publication
count/identity check using active subscriber refs, not a text-read privilege.
Search/chunk/evidence access still requires that worker owner's own membership.

Only import jobs may index, only stopped operator maintenance may force reindex
or staging/global GC, and ordinary AI jobs cannot invoke central cleanup/delete.
Imports may clean only their own obsolete runs. A retired run busy with another
reader is retained for later GC rather than invalidating a successful replacement.

Physical source deletion is a durable 02 delete job. At the writer fence, 04
checks zero memberships and no other queued/running jobs referring to the source.
The backend must atomically mark the source `deleting` under its SQLite writer
lock and reject new imports/read jobs while deletion is in progress. This tombstone
protects the asynchronous vector-delete interval; 04 does not hold SQLite open
across a Chroma await or claim a distributed transaction. Cleanup rechecks under
the writer lock before vector deletion and before forgetting metadata. A deleting
run with memberships or a run with active readers is refused and retained.

Maintenance remains an operator-only local command with stopped API/workers,
explicit source selection and the existing SQLite/Chroma pairing guard. Do not
expose `MaintenanceExecution` or Python context constructors as LLM/browser tools.
`--workers-stopped` is an assertion, not an inter-process process-stop mechanism.

## Upgrade and rollback

1. Finish 02's backed-up ownership migration/explicit legacy assignment while stopped.
   Follow `02_api_backend/AUTH.md`; do not assign old data to the first login.
2. Use the same runtime profile/env files for every 04 operator command. Inspect
   `yk-rag config`, then run stopped `yk-rag init` to add `rag04_security` and its
   persistent cursor signing key. Initialization is additive and repeatable.
3. If the store is not already paired, perform the existing verified
   `yk-rag bind-store --workers-stopped` procedure. Existing pair IDs are retained.
4. Restart with authenticated 02, then verify two-account search, evidence, cursor
   rejection and detach/shared-source behavior before exposing the combined system.

The manifest table schema remains v1, chunk JSON remains v2, and embedding inputs,
vector metadata and fingerprints are unchanged. No bulk reindex/re-embedding is
required for this permission change. Existing unsigned cursors intentionally expire.
Keep `rag04_security` private as part of the application SQLite backup. Back up and
restore SQLite and the entire Chroma tree/marker together while stopped; follow 02's
ownership rollback procedure rather than downgrading populated identity tables.

Pre-auth 02 is supported only for historical `APP_ENV=test` fixtures. With the new
backend, `AUTH_ENABLED=false` remains an explicit development/test compatibility
mode; it is refused in production. Missing authenticated backend/schema/authorizer
fails closed. This compatibility mode is not multi-user authorization.

## Repeatable integration checks

After 02 merges, normal `pytest tests` runs all account cases automatically. Before
merge, the following runner exports only a pinned 02 `src` snapshot into ignored
04 runtime storage and sets a child process's `PYTHONPATH`; it never edits 02's
checkout, imports its changes into this branch, or migrates existing app data:

```powershell
uv run --locked python scripts/check_account_contract.py --backend-ref f406d326a8545d1f2468a7ea3c074c5144a80a9b
docker compose -f compose.test.yaml -p yk04-authorized build tests persistence
uv run --locked python scripts/check_account_contract.py --backend-ref f406d326a8545d1f2468a7ea3c074c5144a80a9b --docker-image yk04-authorized-tests
```

The Docker dependency snapshot is read-only, network access is disabled and keys
are empty. Fixtures use real backend repositories/migrations and real Chroma with
labelled deterministic embeddings. They seed trusted test principals; they do not
claim to exercise Google browser login or real Gemini semantic quality.
