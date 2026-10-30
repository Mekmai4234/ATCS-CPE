# Auth/UI verification — 21 October 2026

Historical report. For the 22 October review fixes and pinned current candidate, see
[REVIEW_AUTH_FIX_REPORT.md](REVIEW_AUTH_FIX_REPORT.md).

## Result

07 verification infrastructure is implemented; **multi-account release acceptance is
blocked**. No module 01–06 production source was edited or pending PR merged. All tests
used disposable state. No real Google account, Gemini request, live captions, legacy
migration on user data or public deployment was performed.

## Revisions

Base develop: `69f534730669f59051a453d9833a0be88695f263`.
The isolated candidate used complete modules from these immutable commits:

| Module | Commit | PR |
| --- | --- | --- |
| 01 | `b2319f7e328905876fb864679420d0987e20cc46` | 17 |
| 02 | `f406d326a8545d1f2468a7ea3c074c5144a80a9b` | 18 |
| 03 | `4b051318b5816c6bc247a038f48eff6d21b7e741` | 19 |
| 04 | `d4aa52d137b44f9217923bd18afc77b6a00881ef` | 20 |
| 05 | same as base develop | no pending auth integration supplied |
| 06 | `84fb1b6e40f3dd685df4c8d300ba058612de6c09` | 21 |

## Executed results

Host: Windows, Python 3.11.16, uv 0.12.9, pnpm 11.25.0, downloaded Playwright Chromium,
Docker Desktop Linux containers. Commands are in [AUTH_ACCEPTANCE.md](AUTH_ACCEPTANCE.md)
and [AUTH_DEPLOYMENT.md](AUTH_DEPLOYMENT.md).

| Check | Result |
| --- | --- |
| Base Python 02/03/04/05/06 + 02 integration/full | **453 passed** |
| Final 07 acceptance | **17 passed**; strict auth and regression cases run separately |
| 07 separate regression gate | **4 passed** |
| Base Ruff check/format, final 07 checks | **passed** |
| Strict auth on base without 02 identity | **nonzero as intended**, explicit contract-missing assertion; no skip |
| Candidate 07 strict auth | **10 passed**, including one real 03–06 domain pipeline |
| Candidate upstream suites combined | **537 passed, 8 failed, 21 errors** across 566 cases |
| Base frontend | typecheck/build passed, **46 unit tests passed** |
| Candidate frontend | typecheck/build/production isolation passed, **57 unit tests passed** |
| Frontend format | normal CRLF checkout warned; `--end-of-line auto` passed on both, Git source is LF |
| Base browser | **30 passed, 1 skipped** (upstream backend-only opt-in) |
| Candidate browser | **47 passed, 1 skipped**, including session/admin/expiry/switch/cache/keyboard/contrast |
| Candidate demo screenshots | login/admin at 375/768/1440 px; upstream login/home at same widths |
| Python API image build and actual fresh API/worker startup | **passed**, all 9 capabilities; schema 0001, single_user=true |
| Base and candidate web images build + actual container TLS/header/SPA checks | **passed**, local CA only, containers removed |
| Prospective auth Compose rendered config | **passed**, API ports removed, shared state retained, evidence read-only |
| Auth release preflight | **blocked as intended**, missing backend identity/client ID/secure HTTPS/evidence |

The 474 base Python checks consist of 453 upstream + 17 final 07 acceptance + 4
regressions, with final checks rerun after added tooling tests. Nine candidate auth cases
use real 02 routes/database with FixtureAdapters and a test-only identity verifier.
The tenth uses actual IngestionService, RagAdapters/Chroma, AnswerAdapters and AgentService,
tests A import/chat/citations/research/quiz, denies B private IDs and verifies logout.
Its captions/metadata/embeddings/models and Google identity are external test doubles.
The existing single-user domain regression explicitly selects auth=false only in test
settings; the separate strict domain test always sets auth=true. Upstream 02's 96 passing
cases include locally signed RSA token validation, schema 0002 migration on a copy,
paired backup, legacy quarantine/explicit claim and GC reader fencing.

## Integration defects kept visible

| Module | Reproduction and observed failure |
| --- | --- |
| 03 | 7 failures: acceptance script + HTTP ingestion integration fixtures make unauthenticated requests; new 02 returns `authentication_required` / 401 |
| 05 | 14 setup errors in `tests/test_integration.py`: existing HTTP fixtures import without a session and expect 202; new backend returns 401 |
| 06 | 7 integration setup errors + 1 evaluation failure: HTTP/session or durable job ownership context is absent; `authentication_required` |
| 01 ↔ 02 | PR 17 explicitly ships PendingSessionPort as production default. SessionPort/GIS browser mocks are separate contracts; they are not a real Google-to-02 adapter |

These are cross-module integration blockers, not fixed by editing their source or
disabling auth. The candidate run exits nonzero and retains every failure in JUnit/logs.
Module 04's 126 tests, 02's 96 tests, 02 integration's 9 and full's 32 passed.

Visual spot-checks of desktop login, mobile home and mobile admin showed readable Thai,
explicit DEMO labels and no visible clipped content in those captured views. This is
fixture visual inspection, not pixel comparison against an attached design reference
or proof of production data isolation. Representative images are in `evidence/auth-ui/`.

## Local evidence locations

All paths below are relative to 07 and ignored runtime output; they remain available in
the workspace. The summary and representative fixture images are committed for review.

- `runtime/20261021T150637088567Z/`: complete initial base run (472 checks at that time).
- `runtime/20261021T152419487128Z/`: final 17-case 07 acceptance.
- `runtime/20261021T152435825258Z/`: final Ruff checks.
- `runtime/20261021T151944018683Z/`: base strict-auth refusal.
- `runtime/candidate-22d4935f94/candidate.json`: exact module provenance.
- Candidate `07_testing_deployment/runtime/20261021T150809290394Z/`: all upstream candidate results.
- Candidate `07_testing_deployment/runtime/20261021T152321774480Z/`: final 10-case auth run.
- `runtime/base-browser.log`, candidate `frontend-browser.log`: browser outcomes.
- `runtime/yk07-startup-549e1a842ef1/`: API/worker startup, HTTP health and cleanup.
- `runtime/yk07-web-ce47719e96/`: base web local TLS check.
- Candidate `07_testing_deployment/runtime/yk07-web-*/`: new web local TLS check.

The active GitHub workflow is included; remote run status must be read from the PR's
checks, not inferred from local tests. Auth acceptance must be repeated after the real
module merges. Real Google staging, integrated browser/backend flow, the production
auth-enabled factory/deployment stack, migration/deploy drill and public HTTPS remain
unaccepted release gates.
