# Module 06 — PR #11 dependency review fixes

Verified on 2026-10-20 (Asia/Bangkok), working from `a66b249`.
Only module 06 is changed. Verification was completed before publication for review.

## Review findings and fixes

The supplied review identified a P1: adding module 05 to the public agent's dev dependencies
changed the local-package metadata recorded by existing consumer locks. Reproduced before
the fix: `uv lock --check --offline` failed for 02/integration and 05 with "lockfile needs
to be updated". This prevented locked installation before application startup.

The fix takes the review's dependency-isolation option:

- Restore the public agent's project requirements, dev group and uv source mappings to
  their pre-PR-11 dependency metadata. No runtime dependency was added or removed.
- Put the real-05 checks in a non-package `acceptance/` project with its own manifest/lock.
  Its local 05 dependency is no longer recorded as part of the public agent package.
- Relocate the same two comparison/cancellation tests into acceptance/tests; keep the other
  75 checks in the core suite. The combined environment runs all 77, with no silent skips.
- Provide separate Docker targets/services for core (02/04/06 only) and acceptance (adds 05).
  Both use `uv sync --locked`; no --frozen or unlocked-install workaround is used.
- Move the default JSON dataset into `src/youtube_agent/data/acceptance.json` and load it
  with `importlib.resources`. Installed wheels and consumer images now carry the dataset
  without needing to copy a separate repository-level 06/fixtures directory.
- Update operating documentation and retain previous reports as historical verification.

No consumer manifest, lockfile, Dockerfile or test was edited. The controller, citation
checks and partial-result behavior were not changed in this dependency repair.

## Verification

| Check | Result |
|---|---|
| Core public manifest dependency metadata vs original `bbf49c4` | Identical |
| Core environment without module 05 installed | **75 passed**, 0 skipped |
| Acceptance-only environment | **2 passed**, 0 skipped |
| Combined Windows environment | **77 passed**, 0 failures/errors/skips |
| Core Docker target | **75 passed**, 0 failures/errors/skips |
| Combined acceptance Docker target | **77 passed**, 0 failures/errors/skips |
| Ruff lint / formatting, host and acceptance Docker | Passed, 14 Python files |
| Built wheel dataset resource | Present, 3262 bytes |
| Original 02/integration Dockerfile build | Passed with its existing lock/context |
| Original pending-07 Dockerfile build in isolated snapshot | Passed |
| Evaluation checks inside pending-07 image | **5 passed**, no separate 06 fixtures copy |
| Existing 05 suite after locked installation | **66 passed** |
| Existing 02/full suite after locked installation | **26 passed** |
| Existing 02 + integration suite, final rerun | **77 passed** |

Windows combined-suite time was 105.66 seconds; core Docker 42.87 seconds; combined Docker
51.45 seconds. These are observations under concurrent build/test load, not performance
benchmarks. All test runs use fixtures/HTTP mocks; no live Gemini or YouTube calls were made.

The original 02/integration Docker build was verified through all locked install and test
image build steps. Its docker-container builder retained the build in cache (no --push
or image publication). Runtime test claims above concern the 06 and pending-07 images.

## Consumer lock and install checks

`uv lock --check --offline` passed for these eight projects in the checkout:

1. 02_api_backend
2. 02_api_backend/integration
3. 02_api_backend/full
4. 03_video_ingestion
5. 04_rag_knowledge
6. 05_ai_answers_analysis
7. 06_research_learning_agent
8. 06_research_learning_agent/acceptance

It also passed for a ninth project: pending 07 at local ref
`origin/feature/07_testing_deployment@a0b2cec9ee4a03be0878e8f8d98efe18b3457fb3`, overlaid with
the current consumer manifests/source and corrected 06 in an isolated snapshot under
06/runtime. No branch was checked out or merged for this check.

Actual `uv sync --locked` succeeded for core 06, its acceptance environment, 02/integration,
02/full, 05 with its team extra, and the pending-07 snapshot. Consumer virtual environments
were redirected under 06/runtime; their existing locks were not regenerated or rewritten.
The other checked projects' locks do not include the agent package.

## Execution note

The first combined 02/integration host run had 76 passing checks and one timeout waiting
15 seconds for a model-start event while multiple builds/suites ran. The failed case then
passed in an isolated rerun without any source/test changes. The final complete rerun
passed all 77 checks in 71.28 seconds and is recorded separately in
runtime/dependency-consumer-integration-final.xml.
This timing failure is not hidden or presented as a successful initial run.

## Reproduction and limits

See README.md and acceptance/README.md for the separate locked test environments and
Docker commands. The pending-07 snapshot check does not claim the entire 07 release suite
passed; it verifies lock/install/build compatibility and the five 06 evaluation checks
specifically affected by missing dataset copies.

Ignored evidence under runtime includes dependency-core-local.xml,
dependency-acceptance-local.xml, dependency-combined-local.xml, dependency-core-docker.xml,
dependency-combined-docker.xml and consumer test XML reports. runtime/wheel contains the
verified wheel; consumer-snapshots/pending07 contains the isolated compatibility snapshot.

Source, tests and documentation are ready for review. Local runtime evidence is excluded from version control.
