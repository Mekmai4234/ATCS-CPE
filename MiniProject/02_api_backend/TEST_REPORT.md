# Backend verification report

Date: 2026-10-17 (Asia/Bangkok)

Scope: module 02 implementation in the local working tree. Modules 03-06 are
represented by explicitly labelled deterministic adapters; no live provider was used.

## Environment

- Windows, Python 3.11.16, uv 0.12.9.
- FastAPI 0.143.3, Uvicorn 0.54.0, SQLAlchemy 2.0.55, Alembic 1.20.0.
- Pydantic 2.14.1, pydantic-settings 2.16.0.
- pytest 9.1.1, Ruff 0.17.1. Exact resolved dependencies are in uv.lock.
- Isolated temporary file-backed SQLite databases and real Alembic migrations.

## Results

| Check | Observed result |
|---|---|
| `uv run --project 02_api_backend --locked pytest 02_api_backend/tests -q` | **56 passed**, 15.57 seconds, no warnings |
| `uv run --project 02_api_backend --locked ruff check 02_api_backend` | Passed |
| `uv run --project 02_api_backend --locked ruff format --check 02_api_backend` | Passed |
| `git diff --check` | Passed |
| Source distribution and wheel build | Passed |
| Install built wheel in an isolated environment | Passed |
| Installed-wheel migrations, fixture import/index worker, mode checks and OpenAPI | Passed |

Test suite duration is a test-run observation, not an application latency or throughput claim.
Build/smoke artifacts are under ignored runtime/ paths.

## Docker verification

Docker was tested on the same date using Docker Engine 29.8.0, Docker Compose 5.5.1
and Linux containers on Docker Desktop. The pinned Python image runs Python 3.11.17
(Debian Bookworm); runtime API/worker use UID 10001.

Command from MiniProject:

```powershell
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_smoke.py
```

Observed results:

| Docker check | Result |
|---|---|
| Build runtime and test targets from uv.lock | Passed |
| Full pytest suite inside Linux as a non-root user | **56 passed in 20.43 seconds**, no warnings |
| Migration-first startup and API health | Passed |
| Separate API/worker containers sharing a named volume | Passed |
| HTTP imports: ready, duplicate, invalid, missing-caption, permanent failure, transient retry | Passed |
| Chat citations, replay without duplicate work, insufficient evidence, transcript pagination | Passed |
| Background summary/comparison, research events, quiz/flashcards/study-plan persistence | Passed |
| Queued cancellation, force-recreated API/worker, durable queue and history | Passed |
| Deletion and unavailable historical citation sources | Passed |
| Automatic cleanup of the unique test containers/network/volume | Passed; no project resources remain |
| Default/test Compose configuration validation, Ruff and diff whitespace checks | Passed |

The automatically generated report and full build/test/runtime logs are retained locally:

- `runtime/yk02-check-992e8f4948/report.json`
- `runtime/yk02-check-992e8f4948/docker.log`

The script generated this project name, used an available localhost port and its own
named volume, then removed only that test project's containers/network/volume. Host
application data was not mounted. Docker images/build cache remain available for reuse.
This Docker test still uses labelled fixtures, not live YouTube, ChromaDB or Gemini.

## Exercised behavior

- HTTPS provider URL parsing, hostile/invalid URL rejection, mixed valid/invalid batches,
  duplicate links and concurrent imports without duplicate video/job records.
- Request/response schemas, OpenAPI, structured error envelopes, request IDs and CORS.
- Durable queued imports, missing captions, unavailable videos and temporary provider failures.
- Atomic worker claims across connections, renewable heartbeat, expired-lease recovery,
  stale-token rejection and graceful interruption/restart.
- Bounded retries, actual due-time backoff, manual retries and deadline preservation.
- No ready status after partial indexing; repeated indexing/transcript writes stay idempotent.
- Captions remain usable when optional title/channel/publication metadata is absent.
- Explicit source scope, channel/date filters, empty/unsupported filters, unknown videos,
  unready videos and comparison minimum-source validation.
- Answer persistence, timestamp links, idempotent chat replay, follow-up history, conversation
  serialization and exclusion of previous turns outside current source versions.
- Rejection of unknown/cross-video citations, altered timestamps, intervals outside the
  stored transcript, invalid model schemas and fabricated coverage counts.
- Replacement of untrusted model URLs with canonical video/timestamp URLs.
- Async analysis/artifact/research jobs, persisted progress/events, partial findings,
  item-level artifact citations, quiz explanations and event/step limits.
- Research cancellation and interrupted runs without resetting/replaying agent budgets.
- Deletion during indexing, cleanup retry, reimport generations and historical unavailable
  source flags; deleted content is not recreated by late application results.
- API/worker as separate OS processes communicating over localhost HTTP and sharing SQLite.
  The worker starts after import acceptance; a fresh API process recovers saved history.
- Migration repeatability, model/schema agreement and downgrade/upgrade on disposable data.
- Refusal to start with an unmigrated database, invalid configuration, streaming enabled,
  production fixture mode, or a database from a different adapter mode.
- Unexpected provider exception text/secrets are absent from API responses and logs.

## Not verified / remaining integration work

- No real YouTube captions/metadata, ChromaDB, embeddings, Gemini account/model access,
  generation quality or autonomous agent was exercised. Connect real 03-06 implementations
  through the documented Adapters protocol, then rerun integration and AI evaluations.
- Citation checks verify reference identity/scope/intervals, not semantic support for every
  generated claim. Processing counts come from 05/06 and still require module 07 evaluation.
- Module 04 must enforce generation/version execution fencing at its independent vector
  publication boundary. The SQL fixture demonstrates application-side behavior only.
- Hard research timeouts fail with retained events; resumable checkpoints are not supplied
  by module 06 yet. Valid partial outputs must be returned before the hard deadline.
- No multi-user authentication, production load/deployment, live-provider quotas, or full
  production backup/restore procedure was evaluated.

Delivery follows the team's feature-branch pull request workflow. These checks establish
backend/offline integration behavior, not production or live-provider readiness.
