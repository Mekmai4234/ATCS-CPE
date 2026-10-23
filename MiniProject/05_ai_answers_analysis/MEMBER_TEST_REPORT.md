# Module 05 member verification — 2026-10-22

## Scope and revisions

Only module 05 is changed by this PR. Base: 02 auth PR #18, revision `b047e80`.
The five supplied task/review files were read as requirements and review evidence;
their earlier candidate results are not treated as results of this change.

The isolated combined candidate pins:

| Module | Revision |
|---|---|
| 02 auth | `b047e809f983ffb2e4f3f9d3e3f074b8976cd6da` |
| 03 member ingestion | `4b051318b5816c6bc247a038f48eff6d21b7e741` |
| 04 authorized RAG | `d4aa52d137b44f9217923bd18afc77b6a00881ef` |
| 05 | This PR's working tree |
| 06 member Agent | `84fb1b6e40f3dd685df4c8d300ba058612de6c09` |
| 07 auth verification | `04c835211ce44f3e914348b302324c351479f41b` |

Sibling branches are copied into an ignored, isolated `runtime/member-*/MiniProject`
tree; no .env secrets, live DBs or sibling deliverables are changed. 05 is installed
with its locked `team` extra, using editable dependencies from that tree.

## Executed checks

| Check | Result |
|---|---|
| 05 full suite with auth 02 and checkout's legacy 04/06 | 114 passed |
| 05 full suite with member candidate above | 114 passed |
| 07 `tests/auth` with the member candidate | 10 passed |
| `uv lock --check` in checkout and combined candidate | Passed (115 resolved packages) |
| Candidate `uv sync --extra team --locked` | Passed |
| Ruff lint and format (`src tests`) | Passed (19 files formatted) |
| `uv build --wheel --out-dir runtime/member-dist` | Passed |
| `git diff --check` | Passed |

The first checkout run exposed a misplaced test assertion in the new lifecycle test;
it was corrected before the passing full runs. The earlier review's 14 integration
setup errors are resolved by authenticated fixtures, without disabling application auth.
The checkout suite was run on `f406d32` before fast-forwarding to `b047e80`; the latter
adds launcher/handoff work and leaves the tested auth/repository contract unchanged.
The member candidate full suite was also rerun on the final `b047e80` base.

Offline identity fixtures use the real challenge/login/session/CSRF path and durable
users/owners, replacing only Google token verification. HTTP tests use actual ASGI
routes, migrated SQLite, worker publication and persistent Chroma. Model, embedding
and transcript sources are synthetic. The SDK itself is exercised with HTTP mocks.

## Covered behaviors

- Authenticated QA, summary, comparison and 06 delegating comparison to 05.
- Anonymous 401 and missing CSRF 403 before model calls.
- A/B sharing a central video and the same question/idempotency key receive distinct
  jobs/conversations. B cannot poll, retry, cancel, read or follow up A's resources.
- A private history marker never enters B's generation payload. Forged history and
  conversation IDs at the direct adapter boundary fail before model calls.
- Out-of-library chat/summary/comparison fail before generation. Admin status does
  not bypass another member's private content or source ownership.
- Removing/replacing a grant during model generation prevents final result publication.
- Detach preserves history with unavailable citations; delete/reimport with a new
  generation does not revive old citations.
- Acceptance session lookup/CSRF refresh works through real authenticated HTTP.
  Mock acceptance covers follow-up/polling/review packets; 401/403 classification,
  actor change, missing session and report redaction are tested separately.
- Existing invalid-citation, cancellation, timeout, partial coverage, resolved-settings,
  provider budget and evidence-version regressions remain in the full suite.

## Reproduce

From MiniProject root, with the pinned sibling revisions and this module installed:

```powershell
python -m uv sync --project 05_ai_answers_analysis --extra team --locked
python -m uv lock --project 05_ai_answers_analysis --check
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 05_ai_answers_analysis/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 07_testing_deployment/tests/auth -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked ruff check 05_ai_answers_analysis/src 05_ai_answers_analysis/tests
python -m uv run --project 05_ai_answers_analysis --extra team --locked ruff format --check 05_ai_answers_analysis/src 05_ai_answers_analysis/tests
```

These are module 05 and targeted auth checks, not a claim that every other module's
full suite passes. No live Google login, Gemini request, real-video semantic evaluation,
browser deployment or production release acceptance was performed. Those require the
assembled system, credentials and explicit human review described in ACCEPTANCE.md.
