# PR #13 review fixes — 2026-10-21

Review input: `05_ai_answers_analysis.md` dated 2026-10-20, reviewing head `74d1737`.
Current integration base: `develop@6520b4c` (02 / PR #9, 03 / PR #14, 04 / PR #10 merged).
The earlier local merge already on this feature branch was preserved. The latest develop
was merged normally, without rewriting history or changing unrelated web test artifacts.

## Changes addressing the review

1. **Acceptance request budget:** replaced the fixed 30-second HTTP timeout with
   `--request-timeout` (default 210 seconds: default 180-second backend job budget + 30).
   Added `--poll-timeout` (default 300 seconds), finite positive validation, separate
   request-timeout diagnostics and report fields for the selected budgets. Connect timeout
   is capped at 10 seconds. These are HTTPX per-operation limits, not a whole-run deadline.
   A timed-out HTTP request may leave a server job running; no automatic resubmission occurs.
2. **Full-flow test consumer:** updated `02_api_backend/full/tests/test_full_flow.py` using
   the compatible 02 implementation at `8780a5e`. It now verifies every actual resolved
   service setting, injects hostile dotenv sources without referring to `team.ENV_FILES`,
   and uses ordinary backend Settings after the launcher's environment export, including
   during resource reopening. No runtime constant was restored to hide the interface change.
3. **Merged runtime and storage safeguards:** the branch includes 02's actual full launcher
   and 04's store binding changes via develop. Updated stale README/acceptance/environment
   notes that previously described these as absent. Existing 02–04 runtime source was not
   independently modified; the only new change outside 05 is the test consumer above.
4. **Locked installation and pending 06/07 compatibility:** checked the actual latest
   manifests/code, rather than assuming the prior transient lock failure still applies.
   05/full/07 locks now check successfully against the selected combined source set; no
   lockfile changes were necessary. Latest 06 no longer has the intermediate dev-dependency
   change described in the older review. Its source was tested without merging its branch.

## Executed checks

Windows, Python 3.11.9. Pytest suites ran in separate processes with `-W error`.

| Current checkout / environment | Observed result |
|---|---|
| 05 complete suite, 05 locked `team` environment | **100 passed**, 97.31s |
| 02 backend + integration + full suites, full locked environment | **103 passed**, 130.57s |
| 03 existing suite, 05 locked environment | **78 passed**, 43.84s |
| 04 existing suite including maintenance/store guards | **97 passed, 1 skipped**, 134.67s |
| Ruff lint and format checks on changed Python files | Passed |
| `git diff --check` | Passed (normal LF/CRLF notices only) |
| Wheel/source-distribution build | Passed, ignored `runtime/dist/` |
| Acceptance CLI / full launcher help | Passed |
| 05 and 02/full `uv lock --check` | Passed |
| 02/full actual `uv sync --locked` | Passed |

Current-checkout suites total **378 passed, 1 skipped**. The skip is 04's opt-in live
embedding test; it was not enabled. New timeout tests inspect the real outgoing HTTPX
timeout configuration and exercise a slow localhost HTTP server with short/long read
budgets. No real-minute sleep is required to verify timeout behavior.

## Isolated combined verification

Created an ignored integration tree under `05_ai_answers_analysis/runtime/combined-20261021-*`.
Copied the current 02/03/04/05 source, including the revised 02 test consumer, excluding
dotenv secrets, existing runtime data, caches and virtual environments. Used `git archive`
to add these exact pending versions:

- 06: `576575fa9eae3cb320f06c40d3a9c3bc7e4be7e3`
- 07: `6ae49e6043f06596c287db42c2cb4d6896e07c4c`

Set `MINIPROJECT_ROOT` and `PYTHONPATH` to that tree and used the installed locked full
environment for external dependencies. Cleared provider keys and disabled live opt-ins.
The real source packages, worker, SQLite and Chroma execute; external providers are doubles.

| Combined-source check | Observed result |
|---|---|
| 02 full suite against revised 05 and latest 06 | **26 passed**, 43.35s |
| Latest 06 complete suite | **75 passed**, 55.29s |
| Latest 07 complete suite, including preflight/system/recovery | **17 passed**, 50.03s |
| Combined 05, 02/full and 07 `uv lock --check` | Passed |
| Combined 05 `uv sync --extra team --locked --dry-run` | Passed |

These are **118 additional matrix executions**, not additional unique tests to add to the
current-checkout total; the 26 full tests intentionally repeat under a different 06 source
version. Latest 07's preflight does not import the deleted 05 constant. No 06/07 source or
lockfile was changed in the deliverable and neither pending branch was merged.

## Reproduce the current-checkout checks

From MiniProject:

```powershell
python -m uv sync --project 05_ai_answers_analysis --extra team --locked
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 05_ai_answers_analysis/tests -q -W error
python -m uv sync --project 02_api_backend/full --locked
python -m uv run --project 02_api_backend/full --locked pytest 02_api_backend/tests 02_api_backend/integration/tests 02_api_backend/full/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 03_video_ingestion/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 04_rag_knowledge/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked ruff check 05_ai_answers_analysis/src 05_ai_answers_analysis/tests 02_api_backend/full/tests/test_full_flow.py
```

The retained local `runtime/combined-latest.json` records the ignored combined tree path;
that tree is not part of the commit. Regenerate it from the revisions above when comparing
future integration changes. Do not include private dotenv files or production data.

## Remaining limits

No live Gemini/YouTube/embedding requests, real-video semantic acceptance or Docker run
was performed in this review-fix round. Structural/mock passes do not establish semantic
support or actual provider/account access. `ACCEPTANCE.md` and the opt-in real plan remain
the workflow for that separate step. No merge of PR #13 is performed by publishing these fixes.
