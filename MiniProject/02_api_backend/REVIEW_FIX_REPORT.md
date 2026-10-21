# Module 02 review fixes — 2026-10-20 (Asia/Bangkok)

Only `02_api_backend` is changed. Verification was completed before commit and PR publication.
The supplied PR review was checked against current repository/PR state rather than
applied as an instruction to merge other work.

## Fix

`full/tests/test_full_flow.py` no longer patches `youtube_answers.team.ENV_FILES`.
That private constant is absent from the new module-05 configuration interface.
No `raising=False` fallback or version-dependent skip was added.

Instead, the fixture uses Pydantic Settings' source hook to substitute hostile
temporary module dotenv files when dotenv is enabled. Explicit `_env_file=None`
remains disabled, as required by the new resolved-settings implementation. User
dotenv files are not used by these substituted service sources.

All four constructed services are checked field-for-field against the full
launcher's resolved settings, including non-default ingestion languages/provider/
timeout, answer pagination/history limits, retrieval settings and agent limits.
The fixture now creates the core backend `Settings` used by actual API/worker
children: module-specific fields must arrive via the exported environment.
The same assertions run after adapter reopen. Startup failures also close the
runtime/database before the fixture exits.

Application runtime, API contracts, other module sources and user data are unchanged.

## Sources verified

| Source set | Identity |
|---|---|
| Actual working branch / current develop base | `6520b4cd2361ce1acd4121a6ea4dd1663c73da10` |
| Module 05 pending PR #13 snapshot | `74d1737e8651725eaa66ab9121df06bd8839a730` |
| Module 06 pending PR #11 snapshot | `576575fa9eae3cb320f06c40d3a9c3bc7e4be7e3` |

03/04 are already merged in the base above. Pending 05/06 were overlaid only in
an ignored isolated copy under `02_api_backend/runtime/compat-20261020/MiniProject`.
The actual checkout's 05/06 files were never replaced. The snapshot import probe
confirmed that 05 has `load_team_configuration`, has no `ENV_FILES`, and 06 has
`AgentSettings.from_backend`.

## Lock finding

The review's dependency finding described an earlier 06 revision. Current PR #11
restores the public agent manifest/dependency metadata and puts its real-05 checks
in a separate acceptance project. Both 02 locks therefore already match current
and pending source manifests.

Re-resolution with `uv lock` produces no tracked lock changes. Both environments
were installed with `uv sync --locked` in the isolated pending-source snapshot;
`uv lock --check` passes for both source sets. No `--frozen` or unlocked install
was used. File hashes are identical between checkout and snapshot:

- `full/uv.lock`: `be5f88efb3837bff0d4349462729e59b3b51819a7c01a663a67bd0946b03a7f3`
- `integration/uv.lock`: `33618d58da3d7701377dd6c6da6b631f644e01d354464134a546223901bd001f`

## Observed tests

All pytest runs use `-W error` and external-call doubles. These are compatibility
checks, not live Gemini/YouTube acceptance.

| Check | Observed result |
|---|---|
| Current base: backend + integration + full suite | **103 passed**, 195.69s |
| Pending 05/06 snapshot: same suites | **103 passed**, 209.27s |
| Final core-Settings flow fixture: current base | **3 passed**, 32.73s |
| Final core-Settings flow fixture: pending 05/06 | **3 passed**, 34.28s |
| Final flow fixture in Linux pending-source full image | **3 passed**, 22.39s |
| Pending-source full Docker image, network disabled | **103 passed**, 166.20s |
| Pending-source integration Docker image, network disabled | **77 passed**, 84.89s |

After strengthening the fixture to use core `Settings`, the three affected flow
tests were rerun on both source sets and in Docker. The Docker targeted rerun
mounted the final test file read-only into the full image; runtime/source package
contents and dependencies were unchanged. Broad suite results above cover the
source-independent dotenv/actual-service assertions and all unchanged tests.

The flows cover import/ready/chat with citations and history, idempotency,
summary/compare, research through the real 05 comparison service, reopen,
durable deletion, cancellation and source changes preventing publication.
The full factory, service logic, SQLite and Chroma are real; external captions,
metadata, embeddings and model responses are explicitly labelled test doubles.

Both Dockerfiles built successfully through their `uv sync --locked` steps using
unchanged consumer locks. The full image packages current 03/04 plus pending
05/06; integration packages 04/06 without requiring 05.

The full-image smoke uses the actual team factory with an invalid test key on an
internal network: non-root API/worker startup, all health capabilities, shared pair
verification and wrong-directory rejection passed. Provider requests are not made.
HTTP import enqueue/cancel and preserved job state after recreating API/worker
also passed. The generated `yk02-check-2e4b7a5706` containers/network/volume were
cleaned successfully; reports/logs remain under the ignored snapshot runtime.

## Reproduce

From the chosen MiniProject source root:

```powershell
uv sync --project 02_api_backend/integration --locked
uv sync --project 02_api_backend/full --locked
uv run --project 02_api_backend/full --locked pytest 02_api_backend/tests 02_api_backend/integration/tests 02_api_backend/full/tests -q -W error
uv run --project 02_api_backend/full --locked pytest 02_api_backend/full/tests/test_full_flow.py -q -W error
uv run --project 02_api_backend/full --locked python 02_api_backend/scripts/docker_full_smoke.py
```

To reproduce pending-source compatibility, use a separate copy of the base with
the current 02 edits and exact 05/06 refs above. Preserve the MiniProject directory
layout, exclude dotenv/runtime/venvs, then run the commands inside that copy.
Rerun lock and compatibility checks when PR source manifests change.
