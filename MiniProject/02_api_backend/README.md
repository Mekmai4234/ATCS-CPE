# Module 02: API / Backend

Free-only outbound policy, shared quota broker and media evidence v2 are documented
in [FREE_TIER_MEDIA.md](FREE_TIER_MEDIA.md). Schema head is 0003. The default denies
unverified Gemini and undeclared legacy provider calls; consumer broker/enrich wiring
is a release dependency. Local operations can be declared independently of Gemini.

Authentication is now required by default. See [AUTH.md](AUTH.md) for Google login,
CSRF, ownership/admin APIs, explicit legacy migration and frontend/deployment handoff.
The historical single-user demo commands below require the explicit development/test
opt-out `AUTH_ENABLED=false`; they are not the authenticated deployment procedure.

Runnable single-user backend for YouTube Knowledge. It implements HTTP contracts,
SQLite persistence/migrations, import coordination, a separate durable worker,
chat history, analysis/research jobs, learning artifacts, cancellation and deletion.

For the full 03–06 system, use the **02-owned full launcher** and configuration/pair
checks in [full/README.md](full/README.md). It delegates to the existing 05 team factory.
The older [integration environment](integration/README.md) connects only 04/06;
03/05 are unavailable in that smaller environment. The default `unavailable` mode reports missing adapters
explicitly. `fixture` mode is a deterministic integration sandbox:
it does not fetch YouTube, create embeddings, use ChromaDB, call Gemini, or run an
autonomous agent. Every fixture answer/title is labelled and HTTP responses carry
`X-Adapter-Mode`. Passing fixture tests does not validate AI quality.

## Install and run (PowerShell)

Run these commands from the **MiniProject root** with Python 3.11-3.13 and uv:

```powershell
uv sync --project 02_api_backend --locked
uv run --project 02_api_backend --locked yk-db upgrade head
```

The committed `uv.lock` pins the tested environment. Migration is explicit and
repeatable; the API/worker refuse to start against an uninitialized schema.
The default database is `MiniProject/runtime/app.db`, independent of the working
directory. `runtime/` and `.venv/` are ignored by Git.
An installed wheel discovers the repository from its current directory/ancestors;
when running outside that tree, set `MINIPROJECT_ROOT` to the absolute project root.

For a fixture demonstration, start the API in terminal 1:

```powershell
$env:ADAPTER_MODE = "fixture"
uv run --project 02_api_backend --locked yk-api
```

Start the worker in terminal 2, also from MiniProject:

```powershell
$env:ADAPTER_MODE = "fixture"
uv run --project 02_api_backend --locked yk-worker
```

Both processes must use the same database and adapter mode. They use
`APP_ENV=development` by default. Fixture mode is rejected in other environments
except `test`. Stop each process with Ctrl+C. To process at most one due job:

```powershell
uv run --project 02_api_backend --locked yk-worker --once
```

Use a **separate DATABASE_URL** when changing adapter modes. Startup/new-job checks
reject a database containing jobs from another mode, so synthetic knowledge cannot
silently become a live library after a configuration change.

Open [Swagger UI](http://127.0.0.1:8000/docs),
[OpenAPI](http://127.0.0.1:8000/openapi.json), or
[health](http://127.0.0.1:8000/health). `/health` checks the DB revision and reports
adapter configuration. It does not claim live provider access has been verified.

The equivalent module entrypoints are `python -m youtube_backend db upgrade head`,
`python -m youtube_backend api`, and `python -m youtube_backend worker --once`
inside the installed environment.

## Fixture demonstration

```powershell
$body = @{ urls = @("https://youtu.be/dQw4w9WgXcQ") } | ConvertTo-Json
$import = Invoke-RestMethod http://127.0.0.1:8000/api/videos/import -Method Post -ContentType "application/json" -Body $body
$jobId = $import.jobs[0].job_id
Invoke-RestMethod "http://127.0.0.1:8000/api/jobs/$jobId"
```

Wait until `stage` is `ready`, then ask:

```powershell
$body = @{ question = "Explain RAG"; scope = @{ video_ids = @("dQw4w9WgXcQ") } } | ConvertTo-Json -Depth 4
Invoke-RestMethod http://127.0.0.1:8000/api/chat -Method Post -ContentType "application/json" -Headers @{ "Idempotency-Key" = "demo-turn-1" } -Body $body
```

Reuse that key only for the exact same request. Change the key for a new turn.
Fixture captions are synthetic lessons, unrelated to the real contents of the URL.
Any valid video ID uses those lessons except the reserved fixture IDs:

| ID | Fixture outcome |
|---|---|
| `NoCaption01` | `no_transcript` |
| `Unavailable` | Permanent `video_unavailable` failure |
| `RetryOnce01` | First attempt times out; next attempt succeeds |

An unrelated question returns `insufficient_evidence` in this deterministic demo.

## Configuration and Gemini

Settings load `MiniProject/.env` and the optional `02_api_backend/integration/.env`
explicitly; the integration file overrides the shared file, and process environment
variables take precedence over both.
Copy `.env.example` only if no local `.env` already exists. API keys are never
required for offline tests. Streaming is not implemented and enabling it fails
configuration validation.

Keep `LLM_MODEL=gemini-3.5-flash` configurable as requested. Module 06 supplies the
Agent Gemini gateway; module 05's answer generation is not implemented yet. This backend
stores requested/returned model metadata, usage and latency supplied by adapters.
The compatibility/routing note remains in `05_ai_answers_analysis/env.txt`.
No Gemini SDK call or account/model-access test has been performed by this module.
Module 04 now uses Gemini embeddings; the 02 integration template reflects that change.
The older shared root template may still contain the superseded OpenAI proposal.

## Connect modules 03-06

For the supplied 04/06 implementation, use `youtube_backend.team:create_adapters`
and the dedicated integration environment. It shares the RAG service between evidence
and Agent tools, centralizes configuration, and closes Gemini/Chroma at shutdown.
See [integration/README.md](integration/README.md) for offline/live profiles and capabilities.

1. Implement the async `Adapters` protocol in `src/youtube_backend/integrations.py`
   in a trusted, installable team package. Return the Pydantic models in `schemas.py`.
2. Configure `ADAPTER_MODE=custom` and
   `ADAPTER_FACTORY=your_package.integration:create_adapters`.
3. The factory receives `settings` and `repository`, and returns an adapter object.
   API and worker must load the same integration/configuration.
4. Module 02 alone sequences ingest -> persist transcript -> index -> ready.
   Module 03 must not independently enqueue/index the same video.
5. Use `context.remaining_seconds`, `context.check()` and `context.event(...)`.
   Methods must yield to asyncio, honor cancellation, and bound every external call.
   Do not hide blocking work in an uncancellable background thread.
6. For module 04, namespace vectors by video generation/transcript version; enforce
   execution fencing at the vector publication boundary. `delete` removes only
   generations <= its argument. A lease check in 02 alone cannot prevent a stale
   process from writing to an independent external store.
7. Implement `inventory` for actual indexed chunk counts and `evidence` to look up
   exact chunk IDs within authorized sources. Never invent these for validation.
8. Raise application-owned classified `AppError` codes for expected failures.
   Retry transport errors in the coordinator; avoid independent unbounded retries
   in each adapter. No-transcript/permanent failures must not be retried as outages.

See [the API contract](../docs/backend_api_contract.md) for scope, errors,
result schemas, and intentional additions to the original proposed endpoints.

## Tests and checks

```powershell
uv run --project 02_api_backend --locked pytest 02_api_backend/tests -q
uv run --project 02_api_backend --locked ruff check 02_api_backend
uv run --project 02_api_backend --locked ruff format --check 02_api_backend
```

Tests use temporary file-backed databases, actual Alembic migrations and fixtures.
They also run API and worker as separate processes over real localhost HTTP,
restart the API, and verify history persistence. No paid service is called.

## Docker / Compose

Docker Desktop must be running with Linux containers. From MiniProject:

```powershell
$env:ADAPTER_MODE = "fixture"
docker compose up --build -d --wait api worker
```

Open [Swagger UI](http://127.0.0.1:8000/docs). Set `BACKEND_PORT` before starting
if 8000 is occupied. API/worker use the same named `backend-data` volume, separate
from the host `runtime/app.db`. An initial migration container must exit successfully
before API/worker start. API health is checked over HTTP. Both processes run as UID
10001; production dependencies are installed from uv.lock in the runtime image.
Base Python and uv images are pinned by digest. The build context excludes local
credentials, runtime data and host virtual environments.

```powershell
docker compose logs --tail 100 api worker
docker compose down
```

`down` keeps the named volume. Do not add `--volumes` to this command when you
want to preserve your demo data. To switch fixture/unavailable/custom modes, use
a different Compose project (for example `docker compose -p youtube-live ...`),
because the persisted database rejects mixing adapter modes.

The provided Compose configuration supports the offline/backend setup. Live custom
integration requires adding the real adapter package to the image and explicitly
providing its factory/configuration and server-side credentials; no local .env or
keys are copied into the image.

To run the full suite inside Linux alone:

```powershell
docker compose --profile test build tests
docker compose run --rm --no-deps tests
```

To repeat both the Linux suite and the API/worker integration test automatically:

```powershell
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_smoke.py
```

This script builds images, runs pytest, then tests real HTTP imports, citations,
idempotency, missing evidence, summary/comparison, research, all artifact types,
cancellation, container recreation with retained history/jobs, and deletion. It uses
a unique Compose project/volume and an available localhost port, forces fixture
mode, and removes only its own containers/network/volume afterwards. JSON results
and build/runtime logs remain in the ignored `runtime/yk02-check-*/` directory.
The standard-library script can also run with a supported `python` directly.

## Operating boundaries and recovery

- This release supports a local single user. Authentication and multi-user ownership
  are not implemented. Future ownership must constrain database AND vector queries.
- Start with one worker on SQLite. Concurrent claims/imports are tested, but throughput
  and production deployment have not been evaluated.
- Leases are renewed while an async operation runs. Recovery waits for lease expiry.
  Stale tokens cannot publish application results. Retry budgets and total deadlines
  are durable; import and other retryable work may run more than once.
- Research runs have one attempt. Without module 06 checkpoints, interrupted research
  fails with retained events instead of restarting an agent with fresh step/time budgets.
  A live agent should return validated partial findings BEFORE its hard deadline.
  On hard timeout, the backend records a failure; it cannot invent partial findings.
- Deletion first hides the video, cancels dependent active work, then queues vector/data
  cleanup. Cleanup failures remain visible and retryable. Poll its job until completion.
- Completed deletion removes transcript/segment/index data. A minimal video tombstone,
  job audit records, saved messages and artifacts are retained. Historical sources are
  marked unavailable. This endpoint is not an account-wide erasure operation.
- For a local backup, stop API and worker cleanly and copy `runtime/` (including the
  module 04 store once integrated). Restore compatible DB/vector versions together,
  apply tested migrations, restart, and verify health plus a cited question. A fresh
  database requires `yk-db upgrade head`. Do not delete an existing database to upgrade.
- These recovery mechanisms are covered by offline/fault tests. A production restore,
  load test and live-provider release evaluation remain work for module 07.
