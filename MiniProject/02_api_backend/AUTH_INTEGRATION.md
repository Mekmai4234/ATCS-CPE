# Auth review integration handoff — 2026-10-22

Module 02 passes its own tests; this is not a whole-system release approval.
Only module-02 tracked files are changed. No other PR is merged by this work.

## Selected module-03 contract

The supported full launcher uses `youtube_answers.team:create_adapters`, with
02's native `Repository.import_urls`, private `import`/`attach` jobs and
`ExecutionContext`. This path already normalizes URLs through 03, shares physical
ingestion and protects library admission, polling, retry, cancellation, transcript
and deletion in 02. See AUTH.md for the public DTOs and source lifecycle.

Do not select `youtube_ingestion.member_adapters:create_member_adapters` for this
release. PR #19 proposes a separate `member_ingestion_backend` contract, different
admission DTOs, shared-claim grants and member quotas/fair scheduling. Repository
does not declare that contract or claim its guarantees. Its explicit
`member_contract_unavailable` failure is expected; it is not a failure of the native
full factory. The full launcher rejects a different factory during validation.
03's wrapper simulation tests do not validate this native path and vice versa.

02 proposes retaining the native path for this integration batch. 03 must align
its acceptance fixtures/docs with that choice, or the team must separately agree
and implement the wrapper's complete contract. The proposal is not represented as
agreement from other module owners. Per-member ingestion quotas/fair claim policy
remain follow-up work; the wrapper's MEMBER_* settings do not configure native 02.

04 PR #20 consumes the durable context and publication fence directly. 06 PR #21
consumes `user_id`, `check`, `authorize_sources` and the leased job, and owns its
execution permit table. A request body never supplies any of these authorities.

For existing bound stores, `yk-full rag-init --workers-stopped` now invokes 04's
additive setup using the same selected full settings and verified SQLite/Chroma
pair. This closes the upgrade gap where repeating `yk-full init` merely verified
an old binding and left PR #20's new cursor signing table absent. The command
requires the stopped assertion, preserves existing keys/bindings and makes no
embedding/model calls. It is distinct from the backed-up ownership migration.

## Pinned candidate and consumer lock patches

| Input | Commit |
|---|---|
| develop / unchanged 05 | `69f534730669f59051a453d9833a0be88695f263` |
| 02 baseline, overlaid with current 02 files | `f406d326a8545d1f2468a7ea3c074c5144a80a9b` |
| 03 / PR #19 | `4b051318b5816c6bc247a038f48eff6d21b7e741` |
| 04 / PR #20 | `d4aa52d137b44f9217923bd18afc77b6a00881ef` |
| 06 / PR #21 | `84fb1b6e40f3dd685df4c8d300ba058612de6c09` |
| 07 / PR #22 (lock check only) | `04c835211ce44f3e914348b302324c351479f41b` |

`handoff/consumer-locks/*.patch` contains six proposed lock updates, produced by
uv 0.12.9 in an isolated candidate. Each refreshed lock passes offline `uv lock
--check` against these pinned module manifests. These are review artifacts inside
02, not applied edits to the consumer modules. No dependency versions were
upgraded: they add the backend's google-auth/requests dependency metadata plus
uv-generated lock format/marker normalization in some files.

Module owners should review/apply their patch from the ATCS-CPE Git root after
bringing in 02's dependency manifests, then run their own locked suites. For example:

```powershell
git apply --check MiniProject/02_api_backend/handoff/consumer-locks/04_rag_knowledge.patch
git apply MiniProject/02_api_backend/handoff/consumer-locks/04_rag_knowledge.patch
uv lock --project MiniProject/04_rag_knowledge --check
```

Do not force an outdated patch if its module head changed. Regenerate using the
new exact refs instead. The module-02 checker does not apply these files itself.

## Reproduce without merging or modifying consumer checkouts

From MiniProject, with the refs available locally, Python 3.11+, uv and optionally
Docker Desktop running:

```powershell
uv run --project 02_api_backend --locked python 02_api_backend/scripts/check_auth_candidate.py --prepare-consumer-locks --docker
```

The script exports committed base/03/04/06/07 files into a unique ignored
`02_api_backend/runtime/auth-candidate-*` directory, overlays only non-ignored 02
files, and records resolved commit IDs plus SHA256 hashes of the 02 files. It copies
no ignored user dotenv, application database, Chroma tree or virtualenv. It checks
all nine locks, optionally prepares consumer patches only in that copy, then runs
02 core/integration/full tests through the full locked dependency environment.
`--docker` additionally builds and runs the same candidate's offline full test
image and authenticated API/worker startup smoke in a fresh Compose project.
The smoke script cleans its own containers/network/volume and retains logs.

Use `--base-ref`, `--ref-03`, `--ref-04`, `--ref-06` and `--ref-07` to inspect newer
commits. No fetch, checkout, merge, commit or push is performed by this checker.
It intentionally exits **1** while original consumer locks are invalid, even when
prepared copies and backend tests pass. Inspect `report.json` and per-step logs;
`whole_system_verified` is always false because consumer/browser suites are outside
this checker. A prepared patch never silently converts the original lock gate green.

## Remaining owner/release gates

- 01: implement the exact AUTH.md challenge/nonce, credential exchange, session
  restore, mutation CSRF and admin response contract; exercise real browser/backend
  requests rather than only the session-gate placeholder.
- 03/05/06: update anonymous fixtures or create actual trusted test principals;
  retain rejection of foreign source/job IDs. Native 02 tests do not repair those
  modules' independently failing suites. 04 also needs its consumer lock update.
- 07: apply its consumer lock update and rerun combined CI, browser/backend and
  container acceptance with authentication enabled. This document does not certify
  PR #22's whole-system verification or browser/Google login.
- Operators: rehearse paired SQLite/Chroma migration **and restore** on stopped
  disposable copies, then assign legacy owner/admin explicitly. Tests use temporary
  stores; they do not authorize migration of existing application data.

See AUTH_TEST_REPORT.md for observed results. Real Google login, provider calls and
production deployment remain unverified; do not merge 02 alone and label the
multi-account system deployable.
