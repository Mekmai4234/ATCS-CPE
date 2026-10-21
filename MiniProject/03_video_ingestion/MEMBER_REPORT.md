# Module 03 review fixes — 2026-10-22

Read all four supplied review documents: 00_summary.md, 03_review_and_fixes.md,
08_verification.md and 09_system_progress.md. Changes are restricted to module 03.
This report supersedes the 2026-10-21 proposal report. No PR was merged by this work.

## Review findings and fixes

| Review item | Change / result |
|---|---|
| Seven failures with authenticated 02 | Legacy lifecycle tests explicitly set auth_enabled=False on their own fixture. Acceptance now logs in through real challenge/session/CSRF using an explicitly labelled offline Google verifier. All seven affected tests pass against native 02/04. |
| Factory requires nonexistent member_ingestion_backend | Removed the second MemberIngestion/SourceGrant protocol and fake backend. The retained member factory validates native 02/04 support, then delegates to the existing IngestionAdapters composition. Real 02 Repository needs no monkey-patched membership contract. |
| No member path integration | Replaced 29 proposal simulations with 29 native integration cases using two authenticated HTTP clients, real migrations/SQLite, Worker and persistent Chroma. External identity/caption/metadata/embedding values are doubles. |
| Stale consumer lock | Refreshed only 03 uv.lock with native 02 metadata: google-auth and requests dependencies. No package versions were upgraded. --check --offline and --locked pass on the dependency candidate. |
| Misleading quota configuration | Removed MemberSettings and MEMBER_* environment values. Native IMPORT_MAX_URLS admission is tested. Durable per-member pending/running quotas and fair claim scheduling remain upstream work; this PR does not claim them. |
| Container using the same lock | Added a 03-specific Dockerfile consuming 03 uv.lock with --locked and a context allowlist. Build/run could not be executed because Docker CLI/Engine are unavailable locally. This remains an unverified acceptance gate. |

README, .env.example, MEMBER_CONTRACT.md and the English env.txt/step.txt/process.txt
now describe one native flow, actual dependency requirements and remaining limits.
The live-caption acceptance CLI requires --fixture-identity --fixture-embeddings;
its report labels both doubles and real_google_login_evaluated=false. Its isolated
state directory refuses existing data. No test verifier is installed by production
factories, and no global AUTH_ENABLED=false fixture was added.

## Exact validation candidate

- Base: develop 69f534730669f59051a453d9833a0be88695f263.
- 02 PR18: b047e809f983ffb2e4f3f9d3e3f074b8976cd6da (newer than the review's f406d32).
- 04 PR20: d4aa52d137b44f9217923bd18afc77b6a00881ef.
- 03: the source and lock in this PR.

The candidate was assembled from git archives under the ignored local directory
runtime/review03-candidate/MiniProject. Current 03 files were copied there without
.venv/caches; only 03 files are staged in the actual checkout. No checkout, commit or
merge of dependency-module changes was performed. 03's package uses the candidate's
editable 02/04 paths, not the old develop packages in the normal workspace venv.

During final checks, PR20 advanced to 1c1c536de3d2a316cc239b8f21b186cd8169aff8.
Its runtime src/ and pyproject.toml are unchanged from the tested d4aa52d; differences
are documentation, its consumer lock and its contract-check script. The results below
refer to the exact d4aa52d candidate, not an untested claim about every future head.

## Results

| Check | Result | Local evidence |
|---|---|---|
| 03 full suite, --locked, -q -W error | **107 passed**, 80.88 s | runtime/review03-final.xml |
| 02 native backend regression | **96 passed**, 28.50 s | runtime/review03-backend.xml |
| 04 native RAG, -m "not live" | **126 passed, 1 deselected**, 209.17 s | runtime/review03-rag.xml |
| uv lock --check --offline, candidate 03 | Passed, 113 packages | command output |
| uv sync --locked, candidate 03 | Passed | command output |
| Ruff check / format --check, git diff --check | Passed | command output |
| Docker build/run | **Not run: Docker unavailable** | docker version: command not found |

After strengthening the factory case to run the worker with the factory's returned
adapter, that targeted case passed again (1 passed, 4.33 s); lint/format also passed.

03 retains all 78 existing pipeline/SDK/process/lifecycle tests. The removed 29 tests
exercised the abandoned fake membership contract; their replacement 29 cases exercise
native HTTP sessions, CSRF/Origin, private jobs/library denial including admin, forged
ownership rejection, concurrent shared admission, ready reuse with one caption fetch,
private retry/cancel, no-transcript classification and native batch-limit rollback.

The lifecycle cases prove A can detach while B imports/reads, B's private attach can
be cancelled without cancelling A, a final GC waits for an active durable reader,
a revoked reader cannot obtain inventory, and final deletion clears actual Chroma
vectors before a new import uses generation 2. For the reader case, admission uses the
HTTP analysis route and the test manually claims the durable job; answer generation
is not evaluated. The production factory composition test supplies real fixture-backed
03/04 components to avoid paid provider requests, using the real native Repository.

Representative commands from MiniProject (after assembling the stated dependency trees):

```powershell
uv lock --check --offline --project runtime/review03-candidate/MiniProject/03_video_ingestion
uv sync --locked --project runtime/review03-candidate/MiniProject/03_video_ingestion
uv run --locked --project runtime/review03-candidate/MiniProject/03_video_ingestion pytest 03_video_ingestion/tests -q -W error --junitxml=runtime/review03-final.xml
```

The XML files and test databases are ignored local evidence, not committed member data.
No live Google, YouTube or Gemini requests, real account migration, public deployment
or browser login smoke was performed. The live embedding test was deliberately
excluded; it is not counted as passed.

## Remaining release gates

02/04 dependency PRs must be coordinated with consumer locks before merging into a
usable combined system. Do not regenerate this lock against old single-user develop
and treat that as member acceptance. Quotas/fair claims, real Google/browser login,
05/06 isolation, Docker build/run, production configuration and migration/restore
remain separate release work. This PR fixes the module-03 integration regressions;
it does not certify the entire multi-account product as production ready.
