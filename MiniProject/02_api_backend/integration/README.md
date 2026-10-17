# Module 02 integration with 04 and 06

This is a backend-owned composition of the existing, unchanged `youtube_rag` and
`youtube_agent` packages. All implementation/configuration changes in this delivery are
inside `02_api_backend`. It supplies indexing, evidence lookup, inventory, deletion,
research and learning artifacts. Live YouTube import (03) and answer/analysis (05)
remain unavailable and return structured 503 responses before creating doomed jobs.

## Environment and profiles

From MiniProject, install the optional combined environment:

```powershell
uv sync --project 02_api_backend/integration --locked
```

Its own lockfile installs local 02/04/06 packages; no changes to their 04/06 manifests,
source or locks are needed. The lightweight `02_api_backend` environment still works
for original fixture/unavailable modes without installing Chroma or the Google SDK.

To configure the integration, copy `02_api_backend/integration/.env.example` to
`02_api_backend/integration/.env` ONLY if that file does not already exist. The backend
now loads process environment > this optional integration file > MiniProject/.env >
defaults. No user .env file is edited by the application.

The team factory constructs 04/06 settings from 02's resolved configuration, rather
than independently rereading the 04/06 override files. Thus API/worker/agent share
the same key/model, source paths and step/time/finalization budgets. API and worker
must use the same configuration.

| Profile | Behavior |
|---|---|
| `BACKEND_INTEGRATION_PROFILE=offline` | Real 04 Chroma and real 06 controller, deterministic labelled embedding/model doubles. No provider calls. Restricted to development/test. |
| `BACKEND_INTEGRATION_PROFILE=live` | Real Gemini clients from 04/06; requires an explicitly configured server-side GEMINI_API_KEY. No synthetic fallback. |

Both use `ADAPTER_MODE=custom` and `ADAPTER_FACTORY=youtube_backend.team:create_adapters`.
The offline embedding override (fixture-hash-v1, 64 dimensions) is deliberate and part
of this explicit profile; it never pretends to be Gemini. Generation metadata says
`provider=fixture`, with `returned_model=offline-integration-model`.

The generation identifier remains configurable `LLM_MODEL=gemini-3.5-flash`. Embeddings
are independently `EMBEDDING_PROVIDER=gemini`, `EMBEDDING_MODEL=gemini-embedding-2`,
1536 dimensions for live mode. 04's existing `CHUNK_*_TOKENS` names mean conservative
UTF-8 byte budgets, not billable Gemini token counts. The root .env.example still has
the old OpenAI proposal: override it with this 02-owned template for integration.

Use separate SQLite AND Chroma locations for offline/live/legacy fixtures. Jobs persist
their custom factory/profile identity; mixing profiles or loading unidentified old custom
jobs is rejected instead of relabelling prior synthetic data. There is no automatic data
deletion, reindex or conversion. Deliberate legacy migrations need a separate reviewed plan.

## Explicit initialization and offline demo

With the optional integration .env configured for offline mode:

```powershell
uv run --project 02_api_backend/integration --locked yk-backend-init
uv run --project 02_api_backend/integration --locked yk-backend-demo-seed --video-id dQw4w9WgXcQ --video-id jNQXAC9IVRw
```

`yk-backend-init` applies backend migrations and initializes 04's additive manifest in
the same SQLite DB. It does not instantiate Gemini or require a key. The seed command
is explicitly offline-only and uses labelled synthetic captions, not those real videos'
contents. Run seeding **before starting API/worker**, or stop both first. It processes
the seed through the existing backend job/lease/index/ready pipeline and real Chroma.
Public URL import stays unavailable until a real 03 adapter is connected.

Then use two terminals with the same config:

```powershell
uv run --project 02_api_backend/integration --locked yk-api
uv run --project 02_api_backend/integration --locked yk-worker
```

`GET /health` returns capability states (`available`, `unavailable`, `unknown`),
integration profile and `synthetic_data`. Available means configured implementation,
not verified live model access. Health never makes paid provider calls.

Research/artifact routes operate on the seeded ready videos. Live integration may
operate on authorized data imported by a future real 03 adapter. Summary/compare/chat
stay unavailable because 05 has no implementation; research comparison tools receive
06's explicit unavailable observation. Structured output/citations/coverage still pass
02's final validation before storage. Full research coverage is required for completed;
smaller findings are partial, consistent with the existing contract.

## Resource lifetime

Adapters are lazily constructed after DB schema/profile checks, in the execution loop.
Concurrent startup creates one instance. API lifespan and worker finally blocks await
closure of model/RAG resources before disposing the DB, including startup failures and
worker cancellation/SIGTERM. Injected legacy adapters without close remain compatible.
The current private transaction-level lease guard used by 04 is unchanged.

Hard total-deadline expiry now explicitly stops automatic retries even if wall-clock
rounding puts it just before the recorded boundary. A shorter per-chat-call timeout
can still retry inside the total budget. Explicit manual import retry can start a new
bounded budget; interrupted research is still never replayed automatically.

## Docker

The standalone Compose file is inside 02; root Compose and other modules are unchanged.
It uses a separate named volume and defaults to localhost port 8001:

```powershell
docker compose -f 02_api_backend/compose.integration.yaml build api
docker compose -f 02_api_backend/compose.integration.yaml run --rm --no-deps migrate
docker compose -f 02_api_backend/compose.integration.yaml run --rm --no-deps seed
docker compose -f 02_api_backend/compose.integration.yaml up -d --wait api worker
```

It defaults to offline mode. API/worker use the same `/app/runtime` volume for SQLite
and Chroma and run as UID 10001. For a live configuration, explicitly set the profile
and key through server environment and use a DIFFERENT Compose project/volume. Never
bake keys into images or silently reuse offline indexes. Standard `down` retains data.

The Dockerfile-specific allowlist includes only required 02/04/06 manifests/source and
02 tests/lockfile; local .env files, runtime data and host virtual environments are excluded.

```powershell
docker compose -f 02_api_backend/compose.integration.yaml --profile test build tests
docker compose -f 02_api_backend/compose.integration.yaml run --rm --no-deps tests
```

The suite container runs non-root with networking disabled and an empty key. It includes
the original backend tests plus new lifecycle/composition tests. To reproduce separate
API/worker containers, real HTTP, persistence and deletion checks automatically:

```powershell
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_integration_smoke.py
```

The standard-library script builds images, runs the Linux suite and uses a unique
Compose project/volume and available port. By default it removes only its own test
resources. Add `--keep` to retain successful demo containers/volume for inspection.
JSON reports and logs are saved under ignored `runtime/yk02-check-*/`.

## Local verification

```powershell
uv run --project 02_api_backend/integration --locked pytest 02_api_backend/tests 02_api_backend/integration/tests -q -W error
uv run --project 02_api_backend --locked ruff check 02_api_backend
uv run --project 02_api_backend --locked ruff format --check 02_api_backend
```

Tests use temporary SQLite/Chroma and labelled captions/models. They do not verify live
Gemini availability, YouTube ingestion, semantic grounding quality or production capacity.
