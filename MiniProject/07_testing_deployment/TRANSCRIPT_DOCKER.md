# Transcript-first Docker workflow

Use `MiniProject` as the working directory. The supported local entry point is
`07_testing_deployment/compose.transcript.yaml`, project `video-buddy`.
Older compose files remain module-only or reviewed production overlays.

```powershell
docker compose --env-file .env.local -f 07_testing_deployment/compose.transcript.yaml config --quiet
docker compose --env-file .env.local -f 07_testing_deployment/compose.transcript.yaml build
docker compose --env-file .env.local -f 07_testing_deployment/compose.transcript.yaml up -d --wait
docker compose --env-file .env.local -f 07_testing_deployment/compose.transcript.yaml ps -a
docker compose --env-file .env.local -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps transcript-import python -m youtube_ingestion.document_cli dry-run --root /app/Transcript
docker compose --env-file .env.local -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps transcript-import
```

The import command is an explicit trusted local operator action, not a public
upload API. It validates all five allowlisted files first, then publishes one
immutable version per existing ready clip atomically. It never grants a library
membership, downloads a video, calls an embedder, or fabricates unknown endings.
File hashes and video mappings are in `Transcript/manifest.json`. Existing
captions/indexes and prior document versions remain available. Importing an
already archived version does not reactivate it over a newer version.

| Service | Module | Expected status |
| --- | --- | --- |
| web | 01 | Healthy; only local port 3000 is published |
| api | 02 | Healthy; private Docker network port 8000 |
| worker | 02–06 | Healthy; one writer, durable jobs and heartbeat |
| migrate | 02/07 | Exited(0), a successful one-shot |
| transcript-import | 03/04/02 | Exited(0) after explicit invocation |
| test-01-web through test-07-e2e | 01–07 | Exit 0 after tests; never idle placeholders |

The web image compiles Linux dependencies using the lockfile. `/api`, `/health`
and `/ready` are proxied to `api:8000`; the browser never uses a container-local
localhost API. Local HTTP cookies are deliberately separate from the existing
production HTTPS overlay and its review gate. Do not use this local profile for
public hosting. AI requests continue to require the existing broker, verified
policy and quota; file reads work without a key. No local model is installed.
The existing operator policy directory is mounted read-only at `/app/policy`
(`VIDEO_BUDDY_POLICY_DIR` overrides the host directory). This translates the
host's relative policy file into a container path without copying policy or
secrets into image layers. Missing/expired policy blocks AI, never local reads.

## Per-module tests

Use a separate project. These containers do not mount the user's state volume;
they create their own temporary SQLite/Chroma and use labelled provider doubles.
`test-01-web` and `test-07-e2e` permit internal HTTP/browser traffic; the Python
offline suites have no external network. Optional public YouTube tests are
excluded by the `live` marker and are not evidence of a live import/provider pass.

```powershell
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml --profile test build
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps test-01-web
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps test-02-api
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps test-03-ingestion
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps test-04-rag
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps test-05-answers
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps test-06-learning
docker compose -p video-buddy-test-20261102 -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps test-07-e2e
```

Reports persist in `07_testing_deployment/runtime/transcript-v3-docker`, or set
`VIDEO_BUDDY_REPORT_DIR` to an operator report directory. Container source
fingerprints come from imported wheel contents, frontend source where present,
and the five immutable document files; checkout CI uses `scripts/source.py`.
Fixture success does not certify provider availability or semantic quality.

## Persistence, recovery and rollback

`state` is a named volume containing SQLite/WAL, Chroma and media. Keep one worker.
Stop writers before a paired snapshot. Use SQLite's backup API, copy Chroma and
media while stopped, and record hashes plus the nonsecret configuration/source
fingerprint. Restore to a different, empty project volume first. Verify the
SQLite/Chroma pair marker, document counts, history/feedback and actual lookup.
Restored test copies must not dispatch providers or reset ledger accounting.

```powershell
docker compose -f 07_testing_deployment/compose.transcript.yaml stop web api worker
# Take a stopped paired backup; inspect it and test a separate restore.
docker compose --env-file .env.local -f 07_testing_deployment/compose.transcript.yaml up -d --wait
docker compose -f 07_testing_deployment/compose.transcript.yaml logs --tail 50 api worker
docker compose -f 07_testing_deployment/compose.transcript.yaml down
```

`down` keeps volumes. Never add `-v` or use system-wide prune. If port 3000 is
occupied, identify its owner before switching only this project's host server.
Do not run the prior host worker alongside the Docker writer on a copied ledger.
Do not downgrade populated document tables; restore a compatible stopped backup
and preserve accounting for any calls dispatched after the snapshot.

## Release decision

No stable/main approval follows merely from build success. Require all local
cases, per-module containers, current-source CI, restart/restore, measured
performance and real AI success/quality gates in the v3 plan. Provider outages
or missing human review leave those gates BLOCKED. Unknown timing remains
user-supplied, unverified timing; parser success is not audio alignment.
