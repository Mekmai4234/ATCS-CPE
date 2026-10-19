# 07 — System verification and deployment

This folder owns repeatable checks, release acceptance, packaging and recovery. Changes
are confined to 07. Modules 02–06 already contain implementations; 01 has no runnable web
application in this checkout. The repository-root README and environment example are
outdated: current 04 uses Gemini embeddings, not the root OpenAI example.

## Install and verify

From **MiniProject**, with Python 3.11–3.13 and uv:

```powershell
uv sync --project 07_testing_deployment --locked
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py
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

**The full command is expected to return nonzero while the recorded upstream defects
remain.** These are failing assertions, not xfail/skips or accepted successes. See
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) and [TEST_REPORT.md](TEST_REPORT.md). Passing a subset
does not establish release readiness.

## CI template

`ci/offline.yml` contains Windows/Linux jobs, locked installation and report upload.
GitHub activates workflows only under repository-root `.github/workflows/`; this template
stays here to honor the 07-only boundary. It is **not active CI**. A maintainer can later
install it at `.github/workflows/miniproject-offline.yml`. This template does not activate remote CI.

## Full team containers

`Dockerfile` packages all five Python modules using the 07 lockfile. `compose.yaml` runs
initialization, API and worker against one SQLite/Chroma volume through the existing
`youtube_answers.team:create_adapters` factory. No frontend is added before 01 is ready.

Export `GEMINI_API_KEY` securely in your local terminal and choose an account-accessible
`LLM_MODEL`. No credentials are stored here. From MiniProject:

```powershell
docker compose -f 07_testing_deployment/compose.yaml config --quiet
docker compose -f 07_testing_deployment/compose.yaml build
docker compose -f 07_testing_deployment/compose.yaml up -d
docker compose -f 07_testing_deployment/compose.yaml ps
```

API docs: `http://127.0.0.1:8007/docs`, bound to localhost. Initialization checks effective
runtime/maintenance settings and key presence before initializing schemas. Shared explicit
environment overrides stale root defaults; local .env/keys/data/Windows environments are
excluded from image inputs. `/health` checks schema/capabilities, not provider/model access
or an active worker. Complete an import and chat to check readiness. Public hosting needs
an agreed HTTPS/authentication setup; this is a local single-user prototype.

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
- 02/04/05: align runtime/maintenance configuration and physical-store protection.
- 03: fix subprocess cleanup; 07 retains the regression gate.
- 05/06 with 07: human review of supported claims and educational quality.
- 01: runnable UI, citation seek/error states and browser acceptance.

Root documentation corrections and active workflow changes remain outside this edit
scope. Tests do not patch production files. Updated env/step/process describe the actual
07 workflow; report missing frontend/live/container evidence as pending.
