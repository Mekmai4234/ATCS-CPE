# Full-system backend launcher (owned by 02)

This environment installs the unchanged 03–06 packages and uses the existing
`youtube_answers.team:create_adapters` factory. It supports import, indexing,
question answering, analysis, research and artifacts. The older `integration/`
environment intentionally connects only 04/06 and can run an offline demo.

The full factory is **live-only**. No fake provider fallback or offline data seeder
is added to the full runtime. Tests substitute external calls only in test code.
Generation remains configurable with `LLM_MODEL=gemini-3.5-flash`; model/account
availability is not established by startup or health.

## Start from a fresh clone

Run from MiniProject with Python 3.11–3.13 and uv:

```powershell
uv sync --project 02_api_backend/full --locked
```

Copy `02_api_backend/full/.env.example` to `02_api_backend/full/.env` **only if
the destination does not already exist**. Supply a server-side `GEMINI_API_KEY`.
Use a new database AND new Chroma directory; existing fixture, 04/06 integration,
or unbound full-team data is never automatically adopted or deleted.

```powershell
if (-not (Test-Path -LiteralPath 02_api_backend/full/.env)) {
    Copy-Item -LiteralPath 02_api_backend/full/.env.example -Destination 02_api_backend/full/.env
}
```

Fill the key locally before starting API/worker. Do not paste it into command
arguments or commit the resulting `.env`.

```powershell
uv run --project 02_api_backend/full --locked yk-full config
uv run --project 02_api_backend/full --locked yk-full init
uv run --project 02_api_backend/full --locked yk-full check
uv run --project 02_api_backend/full --locked yk-full api
```

In a second terminal, with the same environment and selected file:

```powershell
uv run --project 02_api_backend/full --locked yk-full worker
```

Configuration precedence is **process environment > selected env file > full
defaults**. Default selected file is `02_api_backend/full/.env`; it may be absent
for environment-only deployment. An explicitly selected missing file is an error.
Use `yk-full --env-file C:/path/to/server.env COMMAND` for another file.
The launcher intentionally ignores root and module-local dotenv files, including
the legacy OpenAI example. Remove stale process variables when switching modes.

All 02/03/04/05/06 setting fields are exported to the child's environment before
existing entrypoints load. This overrides their module-local dotenv precedence.
Secrets are passed in the child environment, never command arguments or config
output. Config/check output includes a key-present boolean, no key value.
Paths resolve from MiniProject, independent of the shell working directory.
Direct `yk-api`, `yk-worker` and `yk-rag` commands retain their existing behavior;
use **yk-full** for the common full-system configuration contract.

## Pair protection and maintenance

`init` explicitly applies 02 migrations, the additive 04 schema, and a 02-owned
`backend02_full_pair` table. It creates `.backend02-pair.json` in the new Chroma
directory. A random pair ID, factory/profile and 04's embedding/chunk fingerprint
must match in both stores before API, worker, check, reindex or GC can proceed.
Repeated init verifies the binding. It does not overwrite metadata or rebind data.
Init/config/check never call Gemini or YouTube; API/worker also require a key.

SQLite must be outside the Chroma directory. A swapped folder, missing marker,
changed fingerprint, old factory/profile job identity or unbound database fails
preflight. Missing-state check does not create a database/index. A failed init
can leave an incomplete new pair; it is intentionally not auto-adopted. Select
another fresh pair or inspect/recover it manually. Do not copy marker files to
silence errors. This check is a configuration binding, not an integrity audit of
every vector, a backup verifier or an inter-process maintenance lock.

Stop API/workers and finish/cancel queued jobs before maintenance:

```powershell
uv run --project 02_api_backend/full --locked yk-full reindex --workers-stopped --video-id YOUR_VIDEO_ID
uv run --project 02_api_backend/full --locked yk-full gc --workers-stopped
```

These delegate to unchanged 04 maintenance with the same exported configuration.
04 also checks idle jobs and current ready source versions. The stopped assertion
cannot prove another process is stopped: operators must stop them. Reindex repairs
the same configuration; changing embedding/chunk configuration requires a new pair
and reimport. Automatic migration/adoption is outside this delivery.

## API acceptance flow

Open `/docs` and check `GET /health`: all nine capabilities must be `available`,
`full_pair_preflight=true`, profile `live`, synthetic data false. Availability
means implementation connected; `live_provider_verified=false` remains explicit.
No health probe makes paid provider calls or verifies worker liveness.

1. `POST /api/videos/import` with `{"urls":["https://youtu.be/YOUR_VIDEO_ID"]}`.
   Inspect per-input outcomes, including rejected/reused URLs. Poll returned job
   IDs through `GET /api/jobs/{job_id}` until stage `ready` or a terminal error.
2. `POST /api/chat` with `{"question":"What are the key points?","scope":{"video_ids":["YOUR_VIDEO_ID"]}}`.
   Supply `Idempotency-Key` for retries. A bounded completed chat can return 200;
   otherwise 202 returns a job ID to poll. Do not resubmit a new job while polling.
3. Inspect citations, video timestamps and the saved conversation. Summary/compare
   use `POST /api/analysis`; compare needs at least two ready selected videos.

Real caption restrictions, 03 subprocess behavior, Gemini access and model quality
remain external/module-owned constraints. No 03 implementation fixes are included.

## Docker

The 02-owned full image packages all five Python modules without modifying them.
It runs as UID 10001, excludes local keys/env/runtime/venvs, and uses a dedicated
named volume for SQLite plus Chroma. It does not replace root Compose or build 01.
The optional `full/.env` supplies service settings; container storage paths are
explicitly fixed under `/app/runtime/full-live`. Use the same env file throughout:

```powershell
docker compose --env-file 02_api_backend/full/.env -f 02_api_backend/compose.full.yaml build api
docker compose --env-file 02_api_backend/full/.env -f 02_api_backend/compose.full.yaml up -d --wait api worker
```

The migration service completes before API, and healthy API precedes worker.
Default host port is 8002 (`BACKEND_FULL_PORT` changes it). `down` keeps data.
For maintenance stop API/worker first, then run the maintenance service explicitly:

```powershell
docker compose --env-file 02_api_backend/full/.env -f 02_api_backend/compose.full.yaml stop api worker
docker compose --env-file 02_api_backend/full/.env -f 02_api_backend/compose.full.yaml run --rm --no-deps maintenance yk-full gc --workers-stopped
```

## Verification

```powershell
uv run --project 02_api_backend/full --locked pytest 02_api_backend/tests 02_api_backend/integration/tests 02_api_backend/full/tests -q -W error
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_full_smoke.py
```

The Docker script builds both images, runs pytest without networking, then starts
real full-factory API/worker containers with an invalid test key on an internal
network. It verifies health, pair rejection, HTTP enqueue/cancel and persistence
after recreation. The HTTP client runs inside the API container because Docker
Desktop does not expose this internal test network through host ports. It does
not send videos to real providers. Pytest separately
tests import → ready → chat/analysis/research with labelled external-call doubles
and real services/SQLite/Chroma in temporary storage. The script removes only its
own generated containers/volume, with reports under ignored `runtime/yk02-check-*`.

No existing application data or local credentials are used in verification.
See [FULL_TEST_REPORT.md](../FULL_TEST_REPORT.md) for observed results and limits.
See [REVIEW_FIX_REPORT.md](../REVIEW_FIX_REPORT.md) for the 2026-10-20 test-fixture
repair and compatibility checks against the pending 05/06 configuration changes.

## Handoff to module 07 (not changed here)

Root README, `.env.example`, architecture and Compose still need coordinated
updates to advertise this full setup instead of their historical fixture-only
status. 07 should also own frontend packaging, real-video/live acceptance,
deployment, backup/restore and release instructions. 04 can later consume the
shared configuration/binding contract in its direct CLI. All delivery edits here
remain inside 02; calling old module CLIs directly does not acquire these guards.
