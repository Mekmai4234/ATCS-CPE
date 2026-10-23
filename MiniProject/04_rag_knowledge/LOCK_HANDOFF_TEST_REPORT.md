# 04 consumer-lock and native-contract handoff — 2026-10-22

This follow-up addresses the review of PR #20. Authorization/retrieval logic is
unchanged. Tracked changes remain inside module 04; no PR is merged, no existing
application data is migrated, and no provider key is required for these checks.

## Dependency correction

The original 04 lock fails `uv lock --check --offline` against the account-aware
02 manifest. The committed correction adds the backend's `google-auth` and
`requests` dependency/requires-dist metadata (four lines). All **110 package
versions are unchanged**. These packages already existed transitively in the lock.
The update matches 02's proposed `handoff/consumer-locks/04_rag_knowledge.patch`.

Before #18 merges, installing this lock against old develop is intentionally not
supported. Use the candidate checker below; do not bypass metadata validation with
`--frozen`. After #18 merges, regular `uv sync --locked` uses the compatible backend.

## Exact candidate inputs

| Input | Commit / provenance |
|---|---|
| Base / unchanged 05 | `69f534730669f59051a453d9833a0be88695f263` |
| Complete 02 package, metadata and native integration tests | `b047e809f983ffb2e4f3f9d3e3f074b8976cd6da` (PR #18) |
| 03 source/manifest | `4b051318b5816c6bc247a038f48eff6d21b7e741` (PR #19) |
| 04 | PR #20 `d4aa52d` plus this follow-up's consumer lock and checker; working-file hashes recorded |
| 06 source/manifest | `84fb1b6e40f3dd685df4c8d300ba058612de6c09` (PR #21) |

The checker exports committed dependencies and only non-ignored 04 files into a
unique ignored `runtime/locked-candidate-*` tree. It copies no user dotenv, data,
Chroma store or virtualenv. It removes inherited `PYTHONPATH`/virtualenv overrides,
checks the actual 04 lock offline, creates a fresh candidate-local environment with
`uv sync --locked`, and verifies the installed backend location and distribution
requirements. Importing Chroma is also checked before running the suite.

Docker is built from that **same candidate's** backend `pyproject.toml`/source and
04 lock/source. Build-time locked sync validates the complete metadata; no new
backend is mounted over an image built from old develop. Locked wheel installation
may use the network. Tests use empty provider credentials and disabled container
networking. The checker never regenerates a consumer lock to make its gate pass.

## Selected production contract

04 adopts the native path selected in 02's AUTH_INTEGRATION.md:
`youtube_answers.team:create_adapters`, native 02 Repository/private subscriber
jobs/ExecutionContext and 03 IngestionService. 02 owns membership admission, frozen
scopes, detach and the writer-locked deleting tombstone; 04 consumes durable actor,
source/version, lease/publication and zero-ref/reader fences.

The proposed `member_ingestion_backend` wrapper in 03 is **not activated** or claimed
by this integration. Its separate quotas/fair-claim guarantees are not provided by
native 02 or module 04. This does not certify 03's independent wrapper suite or
resolve other modules' independent fixture/lock work.

For existing stores, stop API/workers, take the paired backup and perform 02's
ownership migration/explicit legacy assignment first. Then use the selected full
configuration with `yk-full rag-init --workers-stopped` to add `rag04_security`.
This preserves the existing key/pair on repeat; repeating `yk-full init` alone is
not the additive upgrade. Follow AUTHORIZATION.md for the direct 04 equivalent.
Unsigned cursors expire as documented. No ownership vector rewrite or bulk
re-embedding is required. Restore SQLite and the whole Chroma tree/marker together.

## Verification and limits

Candidate: `runtime/locked-candidate-72fd2d9c46`.

| Check | Observed result |
|---|---|
| 04 offline lock check, actual locked sync and installed-backend/Chroma probe | Passed |
| 04 Windows suite, warnings as errors | **126 passed, 1 live-provider skip** in 207.18 s |
| Full offline lock check and actual locked sync | Passed |
| 02 core/integration/native full-factory Windows suite, warnings as errors | **141 passed** in 126.94 s |
| Docker build from the same complete backend metadata and 04 lock | Passed |
| 04 Docker suite, warnings as errors, network disabled | **126 passed, 1 live-provider skip** in 174.52 s |
| Host and Docker Ruff lint / format | Passed; 28 Python files formatted |
| Scope, credential-pattern, whitespace and runtime-file hash checks | Passed; only 04 files changed |

`report.json` records exact dependency refs, source hashes and each phase's exit
code. Host suites have JUnit XML; each phase has a separate log. The submitted
`uv.lock` and checker match the tested candidate byte for byte. The ignored
`runtime/lock-handoff-audit.json` records that comparison and the 110 unchanged
package versions. `runtime/lock-before-refresh.log` preserves the original failure.

The previous source-overlay test results in AUTHORIZATION_TEST_REPORT.md remain
historical; they were not proof that the submitted consumer lock was valid.

An initial deep Windows candidate virtualenv failed to import OpenTelemetry's
`logarithm_mapping` dependency during Chroma startup. The checker now keeps fresh
virtualenvs at shorter paths in its own candidate directory and checks the import
before the suite. No dependency version was upgraded or failing test deselected
to address that harness failure. The failed attempt is not counted as a pass.

No real Google browser login, public deployment, live provider quality evaluation
or production migration/restore is claimed. The external calls are labelled test
doubles; source storage and ownership paths use real SQLite/Chroma/backend code.
The selected native full-factory checks do not replace independent 03/05/06/07
or browser suites. `whole_system_verified` remains false in the candidate report.
Merge/deployment of #18 is still required; this follow-up does not approve the
whole auth-phase release or merge any branch on behalf of other module owners.

## Reproduce

From module 04 (the launcher is stdlib-only and does not need the old checkout's
04 environment to resolve first):

```powershell
uv run --no-project --python 3.11 python scripts/check_account_contract.py --backend-ref b047e809f983ffb2e4f3f9d3e3f074b8976cd6da --full-integration --docker-image yk04-locked-auth
```

`--prepare-only` exports and records inputs without testing or repairing locks.
`--docker-image` always builds the image before testing it. Exact refs, 04 working
file hashes, phase exit codes, logs and JUnit stay beside the candidate in ignored
runtime storage. No changes to another module's checkout are needed to reproduce.
