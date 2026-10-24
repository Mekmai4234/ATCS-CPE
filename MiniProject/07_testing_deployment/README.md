# 07 — System verification and deployment

Current work (24 October): [UI_CHECKOUT_REPORT.md](UI_CHECKOUT_REPORT.md) and
[FLOATING_UI_ACCEPTANCE.md](FLOATING_UI_ACCEPTANCE.md). Backend modules 02–06 are now
merged into develop and the locked environment works on the actual checkout. Default
CI never replaces app sources with `integration.json`. Historical candidate evidence
and the 22 October report remain available, but do not certify a later revision.

This folder owns repeatable checks, release acceptance, packaging and recovery. Changes
are confined to 07 and the authorized repository-root GitHub workflow. Modules 01–06
have runnable implementations; Google identity integration is still pending in separate
module PRs. See [AUTH_ACCEPTANCE.md](AUTH_ACCEPTANCE.md) for the current auth matrix,
candidate commands and release blockers. The repository-root environment example is
outdated: current 04 uses Gemini embeddings, not the root OpenAI example.

## Install and verify

From **MiniProject**, with Python 3.11–3.13 and uv:

```powershell
uv run --no-project python 07_testing_deployment/scripts/source.py record --record 07_testing_deployment/runtime/checkout-source.json
uv lock --check --project 07_testing_deployment
uv sync --project 07_testing_deployment --locked
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py --group auth
uv run --no-project python 07_testing_deployment/scripts/source.py verify --record 07_testing_deployment/runtime/checkout-source.json
```

The 07 lockfile installs 02–06, including 05's `team` extra, pytest and Ruff. Existing
suites run in separate processes, avoiding repeated filenames and `conftest` collisions.
The runner clears provider keys/live opt-ins, deselects live tests, treats warnings as
errors, checks lint/format without modifying other modules, and saves logs/JUnit/JSON
under ignored `07_testing_deployment/runtime/<UTC-run>/`. Suite timeouts terminate their
owned process tree. Local offline execution is not a network sandbox; the Docker test
service additionally disables networking. Existing tests use synthetic provider doubles.

Append `--group baseline` for existing suites, `--group acceptance` for 07 integration/
recovery/tooling, `--group regressions` for upstream blockers, or `--group lint` for Ruff.
`--timeout 900` sets maximum seconds per command (default 900).

Baseline includes `02_api_backend/full/tests` as a separate process. Pytest state uses
fresh short OS temporary paths to avoid deep Windows workspace/Chroma path failures.
Override with `--temp-root C:\t` or `YK07_TEMP_ROOT`; logs/JUnit/JSON stay in 07/runtime.
The report records the temporary-state path, which is retained for failure diagnosis.

Regression gates now check the repaired 03/04 safeguards through supported interfaces,
including exact `index_store_mismatch` errors and unchanged manifests for wrong-store
reindex AND garbage collection. No xfail/skips hide setup failures. See
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) and [REVIEW_FIX_REPORT.md](REVIEW_FIX_REPORT.md) for current
results; [TEST_REPORT.md](TEST_REPORT.md) preserves the historical 19 October baseline.

## Active CI

The default PR/push workflow tests the GitHub merge-test/current checkout directly.
`source.py` records HEAD plus actual source file fingerprints before tests and verifies
them afterward. A changed marker after a pin is covered by `tests/test_source.py`:
the changed source fails its real subprocess and old provenance is rejected. There is
no pinned fallback. Python, frontend and image builds use the same source policy.
Real adapter E2E runs only when that harness exists in the current checkout; otherwise
the job summary explicitly states BLOCKED. Screenshot capture is not UI acceptance.

`miniproject-pinned.yml` is a separately named manual-only historical integration job.
It cannot trigger on a PR or push. Choose it deliberately for an unmerged batch; never
use it to certify later source or replace the checkout regression gate.

On a checkout with module 01's real adapter, run `scripts/browser_identity.py --checkout` with the locked Python environment
after installing module 01 dependencies/Chromium. It runs the real HTTP adapter without
mocking `/api`, with only external GIS/provider fixtures. `scripts/docker_auth.py` checks
the auth-enabled production factory and HTTPS proxy on an internal Docker network.
Neither drill creates release attestation or calls paid providers.

## Full team containers

`Dockerfile` packages all five Python modules using the 07 lockfile. `compose.yaml` runs
initialization, API and worker against one SQLite/Chroma volume through the existing
`youtube_answers.team:create_adapters` factory. The separate `Dockerfile.web` builds module
01 and serves it through Caddy. The guarded auth overlay is described in
[AUTH_DEPLOYMENT.md](AUTH_DEPLOYMENT.md); it is not yet accepted for public deployment.

Export `GEMINI_API_KEY` securely in your local terminal and choose an account-accessible
`LLM_MODEL`. No credentials are stored here. From MiniProject:

```powershell
docker compose -f 07_testing_deployment/compose.yaml config --quiet
docker compose -f 07_testing_deployment/compose.yaml build
docker compose -f 07_testing_deployment/compose.yaml up -d
docker compose -f 07_testing_deployment/compose.yaml ps
```

API docs: `http://127.0.0.1:8007/docs`, bound to localhost. Initialization, API and worker
all resolve `FullSettings` once and export every service field. New 05 uses its resolved
loader; develop's legacy loader is checked under the identical exported snapshot. The
removed `youtube_answers.team.ENV_FILES` constant is never imported. Preflight compares
runtime and maintenance database/vector/fingerprint/model values before initialization.

02's initializer creates/verifies a guarded SQLite/Chroma pair and refuses old unbound
state. All service children receive the same snapshot and verify this pair before startup.
No .env files, keys, data or Windows environments are included in Docker build inputs.
`/health` checks schema/capabilities, not provider access or useful worker completion.
This remains a localhost single-user prototype; public HTTPS/authentication is separate.

For local commands, select one full-system environment file explicitly:

```powershell
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/preflight.py --env-file YOUR_FULL_ENV
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/preflight.py --env-file YOUR_FULL_ENV --initialize
```

`--run api` and `--run worker` use that selected file, require a key and export the same
snapshot. The test image includes 02 full tests and all allowed 06 test/fixtures inputs.
Latest 06 packages its dataset in `youtube_agent/data` inside the wheel; copying the
whole allowlisted 06 directory also supports a fixtures/ directory when present.

Offline container checks mount no application volume and disable networking:

```powershell
docker compose -f 07_testing_deployment/compose.yaml --profile test build tests
docker compose -f 07_testing_deployment/compose.yaml --profile test run --rm --no-deps tests
```

Compose syntax validation alone is not successful image build or deployment. See the
report for actual Docker Engine availability and executed results.

After building the runtime, an isolated startup drill can be repeated with:

```powershell
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/docker_startup.py
```

It uses `compose.startup-test.yaml`, a synthetic key and an internal Docker network.
It verifies initialization, API/worker startup and HTTP health from the worker container
to the API. It does not test the host-published port or make import/model requests.
The helper removes only its randomly named project's containers/network/state volume
and keeps its report under 07/runtime. Test images/build caches are retained for reuse.

## Live acceptance

Use separate live state. Requests persist imports and can incur provider charges, so they
are excluded from default verification. Once the stack is ready:

```powershell
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/live_smoke.py --allow-live --url "https://youtu.be/YOUR_VIDEO_ID" --question "RAG คืออะไร"
```

The script checks live capabilities, imports until ready, asks within scope and validates
citations/intervals/timestamp URLs. On timeout it leaves the existing/shared server job
alone; inspect/cancel it through the API. It does not prove semantic support or click a
player. Perform the manual review in [ACCEPTANCE.md](ACCEPTANCE.md). A configured model
name does not establish access. Existing 03/04 live reports remain historical module
evidence, not a new complete-system acceptance result.

## Recovery and responsibilities

Follow [RECOVERY.md](RECOVERY.md) for cold paired backups with checksums and new restore
destinations. Retain compatible image/schema/embedding/chunk configuration.

- 07: central runner/reports, integration and acceptance, packaging, recovery drill.
- 02/04/05: retain shared configuration and physical-store safeguards as interfaces evolve.
- 03: retain bounded subprocess cleanup; 07 keeps the regression gate.
- 05/06 with 07: human review of supported claims and educational quality.
- 01: runnable UI, citation seek/error states and browser acceptance.

Root documentation corrections remain outside this edit scope. The active workflow was
explicitly authorized. Tests do not patch module production files. Updated env/step/process
describe the current 07 workflow; missing integrated auth/live evidence stays pending.
