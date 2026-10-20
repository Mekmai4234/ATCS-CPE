# Full-system backend verification — 2026-10-19 (Asia/Bangkok)

Base: `develop@25427fe`. All delivery changes are confined to `02_api_backend`.
No 01/03/04/05/06/07 sources, root configuration, user dotenv files or existing
application data were edited. Verification was completed before commit and PR publication.

## Delivered behavior

- `yk-full` validates one selected configuration and exports all service fields
  to API/worker/maintenance subprocesses. Existing module-local dotenv files lose
  to that resolved environment. The real 05 team factory remains unchanged.
- Config diagnostics redact secret fields and explicitly leave provider access
  unverified. Validation failures do not echo raw input values.
- Explicit initialization binds a fresh SQLite/Chroma pair using an additive 02
  table plus an exclusive directory marker. Profile, factory, pair ID and 04's
  embedding/chunk fingerprint must match before full startup or maintenance.
- API/worker recheck binding before constructing adapters when full preflight is
  enabled. Existing lightweight and 04/06-only setups preserve their defaults.
- A separate locked full environment and non-root Docker image package 02–06.
  Setup, maintenance, acceptance flow and the 07 handoff are in `full/README.md`.

## Observed final-source results

| Check | Result |
|---|---|
| Windows 02 + existing integration + new full tests, `-W error` | **103 passed**, 66.78s |
| Linux Docker same suites, network disabled, UID 10001 | **103 passed**, 76.03s |
| Lightweight 02 environment without installed 03/04/05/06 packages | **68 passed**, 16.00s |
| Existing 03 regression in the full environment | **69 passed**, 21.99s |
| Existing 04 regression in the full environment | **77 passed, 1 skipped**, 74.31s |
| Existing 05 regression in the full environment | **66 passed**, 39.77s |
| Existing 06 regression in the full environment | **55 passed**, 22.43s |
| Ruff lint / format | Passed |
| Full lock consistency / Compose config / whitespace checks | Passed |

Regression suites were executed separately with warnings as errors. 04's opt-in
live embedding test was skipped; no live opt-in was enabled. The lightweight
environment was separately checked with `find_spec`: all four optional module
packages were absent.

## Mechanisms exercised

New tests cover selected-file/process precedence, all service-field exports,
hostile module dotenv overrides, redacted diagnostics, module-specific validation,
explicit live-only configuration, identical launcher dispatch for API/worker/GC/
reindex, and runtime rejection before factory construction.

Pair tests cover repeatable initialization, a missing store without auto-creation,
swapped directories from two initialized pairs, changed embedding dimensions,
unbound existing database/index preservation, and SQLite inside Chroma rejection.

Full flow tests construct the actual `youtube_answers.team` factory and use real
03 normalization/service, 04 persistent Chroma/manifest, 05 generation service and
06 controller. Only external caption/metadata, embedding and model calls are
test doubles. All test content and generated model metadata are labelled fixture.
Tests exercise HTTP import → ready → chat/citations/history, idempotency,
summary/compare, research through 05 comparison, resource reopening, durable
deletion, cancellation and source deletion preventing result publication.

The test embedding substitute preserves the requested configuration contract so
the real full factory can be exercised. Its deterministic vectors are confined
to pytest temporary storage; they are not live Gemini vectors or reusable demo
indexes. No runtime switch installs these doubles in the deployed image.

## Docker smoke

Successful project: `yk02-check-37564ea7d6`.

- Built locked full runtime and test images with only allowlisted inputs.
- Ran the 103-test suite with networking disabled.
- Initialized a dedicated new pair, then started separate API and worker
  containers using the unchanged full factory, an invalid test key and an
  internal network with no external egress. No videos were sent to providers.
- Verified all nine health capabilities, `full_pair_preflight=true`, explicit
  unverified provider access, non-root UID, and maintenance pair checking.
- Verified wrong Chroma path rejection before maintenance.
- Stopped worker, enqueued/cancelled import through actual HTTP, recreated both
  containers and verified the cancelled job/pair persisted.
- Removed only this generated project's containers/network/volume successfully.

The HTTP test client runs inside the API container. Docker Desktop host forwarding
on the internal test network refused connections on the initial attempt; the
final script keeps egress blocked and uses internal loopback HTTP instead. The
normal deployment's published host port is not validated by this internal smoke.

Machine-readable report and logs (ignored):
`runtime/yk02-check-37564ea7d6/report.json` and `docker.log`.

## Reproduce

From MiniProject:

```powershell
uv sync --project 02_api_backend/full --locked
uv run --project 02_api_backend/full --locked pytest 02_api_backend/tests 02_api_backend/integration/tests 02_api_backend/full/tests -q -W error
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_full_smoke.py
uv run --project 02_api_backend --locked ruff check 02_api_backend
uv run --project 02_api_backend --locked ruff format --check 02_api_backend
```

The 03–06 regression commands use the same full project with each module's
`tests` directory separately. Selected local versions: Python 3.11.16, FastAPI
0.146.0, Pydantic 2.14.1, google-genai 2.31.0, ChromaDB 1.5.9, pytest 9.1.1.
The complete tested environment is pinned in `full/uv.lock`.

## Limits and handoff

No real credentials, live YouTube/Gemini requests, semantic-quality evaluation,
production/load test, backup restore, legacy-data adoption or model migration
were performed. Underlying 03 subprocess behavior remains owned by 03. Full
capabilities indicate connected implementations, not external service readiness
or worker liveness. Real-provider import → ready → chat remains a live acceptance
step for a configured account.

Pair binding detects configuration/store swaps; it does not audit all persisted
vectors, verify backup completeness, or lock out legacy unguarded commands. Stop
API/workers before maintenance. Actual live reindex/GC on user data was not run.
Embedding/chunk changes require a new bound pair and reimport in this delivery.
Direct legacy module CLIs retain their existing configuration and behavior.

Only 02 docs were updated. 07 still needs to coordinate the root README/env/
architecture/Compose changes, frontend packaging and live acceptance/release flow.
