# Module 07 verification report

Historical 19 October results. See [REVIEW_FIX_REPORT.md](REVIEW_FIX_REPORT.md) for the
20 October follow-up against updated develop and the isolated pending-PR composition.

Date: 19 October 2026 (Asia/Bangkok). Base commit: `25427fe`.
Working branch: `feature/07_testing_deployment`. Verification completed before publication.
All tracked/untracked deliverables are inside `MiniProject/07_testing_deployment`.

## Delivered

- A 07-owned Python manifest/lockfile composing unchanged modules 02–06.
- An offline runner with separate suite processes, timeouts/process-tree termination,
  isolated test state, credential/live-opt-in clearing, JUnit/log/JSON output and read-only
  lint/format checks. A complete failed run remains `passed=false` with exit code 1.
- New combined 02/03/04/05/06 domain-service flow, persistence and actual cold recovery
  tests. External caption/embedding/model providers are explicitly synthetic.
- Ordinary failing regression gates for 03 cleanup, runtime/maintenance configuration
  divergence and wrong physical Chroma store during reindex. No xfail masks them.
- Full-team runtime/test Docker images, shared-config Compose, preflight and an isolated
  startup drill. Runtime/test images use UID/GID 10001; tests have networking disabled.
- Opt-in live smoke utility, recovery utility, acceptance/recovery/known-issues guides,
  updated env/step/process and a passive Windows/Linux CI template.

## Environment

Windows Python 3.11.16, uv 0.12.9; pinned Linux Python 3.11 container image.
07 lockfile: 116 resolved packages; FastAPI 0.148.0, google-genai 2.31.0, ChromaDB 1.5.9,
pytest 9.1.1, Ruff 0.17.1. Docker Engine 29.8.0, Compose 5.5.1.
The 07 environment has its own resolved lock; other module lockfiles were not changed.

## Executed results

| Check | Windows | Linux Docker |
|---|---|---|
| Existing 02 suite | 68 passed | 68 passed |
| Existing 03 suite | 69 passed | 69 passed |
| Existing 04 suite | 77 passed, 1 live test deselected | 77 passed, 1 live test deselected |
| Existing 05 suite | 66 passed | 66 passed |
| Existing 06 suite | 55 passed | 55 passed |
| Separate 02 integration suite | 9 passed | 9 passed |
| **Existing-suite total** | **344 passed** | **344 passed** |
| New 07 acceptance/recovery/tooling | **9 passed** | **9 passed** |
| Known-defect regressions | **3 failed** | **1 passed, 2 failed** |
| Ruff lint and format, 02–07 | Passed (final checks) | Passed |
| uv lock consistency | Passed | Locked image installation passed |

The live test is deliberately deselected, rather than skipped after entering the test.
Other deselection counts come from splitting acceptance and regression groups; they are
not omitted acceptance failures. These totals describe independently executed suites,
not unique production behaviors or measured application performance. Final totals are
353 passed/3 failed on Windows and 354 passed/2 failed on Linux.

Additional checks:

- Main and startup-overlay Compose configuration validation: passed.
- Build full-team runtime and test targets with non-editable local packages: passed.
- Linux offline suites run as non-root with no network/application-volume mount: executed.
- Initialization, API health and separate worker startup with a fresh shared state volume:
  passed in project `yk07-startup-f964c049aae1` (29.671 s including teardown).
  HTTP was checked from the worker container to the API over an internal network. No
  import or generation was submitted. The synthetic key was not a valid provider key.
  Health correctly kept `live_provider_verified=false` while exposing all nine capabilities.
- Startup helper removed its own containers, network and state volume: passed.
- Test container removed after copying its reports; build images/cache retained.
- CI template YAML parsing, Git whitespace and 07-only edit-boundary checks: passed.

## Verified blockers

1. **K03-PIPE, Windows:** a real child emitting 20 MiB did not finish cleanup inside
   the probe's 3-second bound (fetch timeout 0.5 s, production ceiling 8 MiB). Emergency
   draining allowed `invalid_transcript` to complete and the child was reaped. The same
   probe passed on Linux. This is platform-dependent, not an all-platform failure claim.
2. **K04-ENV, both platforms:** a 05-local `.env` override resolves runtime Chroma to
   `runtime/answers05/chroma` while maintenance resolves `runtime/chroma`. The files used
   to reproduce this are isolated test fixtures, not actual application `.env` files.
3. **K04-STORE, both platforms:** reindex accepted another empty Chroma location against
   the same disposable SQLite instead of rejecting before manifest mutation. The test
   requires rejection and preservation of the active manifest; current code fails it.

These are upstream implementation defects. Modules 03/04 were not changed under the
07-only restriction. The default verification gate is intentionally RED pending fixes.
The 07 deployment's explicit settings/preflight reduce configuration divergence but do
not repair module 04's durable physical-store identity checks.

## Artifact locations and reproduction

All paths below are relative to this folder; raw output stays ignored under runtime:

- Windows baseline and defect evidence: `runtime/20261019T142623550908Z/`.
- Final Windows acceptance: `runtime/20261019T143318061463Z/`.
- Final Windows lint/format: `runtime/20261019T143845350949Z/`.
- Docker build logs: `runtime/docker-build.log`, `runtime/docker-runtime-build.log`.
- Linux copied JUnit/log/JSON reports: `runtime/docker-linux/`.
- Docker command output: `runtime/docker-tests.log`.
- Final startup report/log: `runtime/yk07-startup-f964c049aae1/`.

The first Windows run occurred while 07 tooling was still being completed. Its baseline
and regression results remain applicable; its interim formatting failures were corrected
and rechecked using the final runs above. No baseline implementation changed afterward.

Run the commands in README.md. The normal runner and Docker test container exit 1 while
the known blockers remain; that exit is not infrastructure failure or a claimed green build.

## Not verified / remaining work

No real YouTube/Gemini calls, paid generation, real-video semantic scoring, public hosting,
host-published-port acceptance, operational live-volume restore, image rollback or browser
E2E were performed. Cold recovery passed on actual SQLite/Chroma using synthetic reference
content, including identical retrieval identities after removing the original test state;
it is not a production restore claim. Citation checks do not prove every generated claim.

01 has no runnable frontend. Root README/architecture/task assignment and root embedding
defaults remain stale because changes were restricted to 07. `ci/offline.yml` is a template;
GitHub CI is not active until installed outside 07 by a repository maintainer. Provider
access/model availability, operational deployment and AI human review remain release gates.
