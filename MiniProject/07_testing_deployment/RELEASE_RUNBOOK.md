# Release runbook (`video-buddy` local stack)

Operating, recovering and rolling back the release candidate that runs on one machine
at `http://localhost:3000`. It continues [LOCAL_STACK.md](LOCAL_STACK.md), which keeps
the configuration, policy renewal and fallback-model details. The stable-release gate
itself is described in [MAIN_RELEASE.md](MAIN_RELEASE.md).

All commands run from `MiniProject` in PowerShell. `$C` is
`docker compose -f 07_testing_deployment/compose.transcript.yaml`.

## 1. Before any change

1. Record the source: `git rev-parse HEAD` and
   `docker exec video-buddy-api-1 python 07_testing_deployment/scripts/image_source.py verify`.
2. Check the policy expiry (`expires_at` in
   `runtime/free-tier-20261026/gemini-free-policy.json`). It must stay valid for the
   whole operation; renew first if not (LOCAL_STACK.md, "Gemini policy renewal").
3. Confirm no job is `queued` or `running`:

   ```powershell
   docker exec video-buddy-api-1 python -c "import sqlite3; c=sqlite3.connect('file:/app/runtime/app.db?mode=ro', uri=True); print(c.execute(""select count(*) from jobs where state in ('queued','running')"").fetchone()[0])"
   ```

   `paused` jobs are allowed; the worker never resumes them on its own.

## 2. Health

```powershell
docker ps --filter name=video-buddy
docker exec video-buddy-api-1 python 07_testing_deployment/scripts/transcript_runtime.py validate
```

`/health` answers once the API is up; `/ready` also needs a fresh worker heartbeat and
returns 503 until a worker runs. `validate` must report 5 documents / 934 passages for
the current `Transcript/` set and makes no provider calls.

## 3. Cold backup

Tag the images, stop the backend, then copy the state while nothing writes to it.

```powershell
$label = "pre-<label>"
docker tag video-buddy-runtime:local "video-buddy-runtime:$label"
docker tag video-buddy-web:local "video-buddy-web:$label"
$C stop worker api
docker run --rm -v video-buddy_state:/state -v "${PWD}/runtime/backups/<label>:/out" `
  video-buddy-runtime:local python 07_testing_deployment/scripts/recovery.py `
  backup /state /out/bundle --services-stopped
docker run --rm -v video-buddy_state:/state:ro -v "${PWD}/runtime/backups/<label>:/out" alpine:3 `
  sh -c "tar -C /state -czf /out/video-buddy_state-<label>.tgz . && sha256sum /out/video-buddy_state-<label>.tgz"
$C up -d api worker
```

Mount the volume read-write for `recovery.py`: SQLite in WAL mode cannot open
`app.db` from a read-only mount (`unable to open database file`). The services are
stopped, so nothing else writes. `bundle/backup.json` lists every file with its SHA-256;
the `tar` archive is the whole-volume fallback. Media assets live under the state
volume (`media-assets/`), so `--media-source` is not needed for this stack.

## 4. Restore rehearsal (new volume, second stack)

Restore never overwrites data. Rehearse into a new volume and start a second stack
under its own project name; it publishes no port and leaves the live stack running.

```powershell
docker volume create video-buddy-restore_state
docker run --rm --user 0 -v video-buddy-restore_state:/vol `
  -v "${PWD}/runtime/backups/<label>/bundle:/bundle:ro" video-buddy-runtime:local `
  sh -c "python 07_testing_deployment/scripts/recovery.py restore /bundle /vol/state && mv /vol/state/* /vol/ && rmdir /vol/state && chown -R 10001:10001 /vol"
```

Create `restore-override.yaml` outside Git:

```yaml
volumes:
  state:
    name: video-buddy-restore_state
    external: true
services:
  worker:
    environment:
      GEMINI_API_KEY: ""
```

```powershell
docker compose -p video-buddy-restore -f 07_testing_deployment/compose.transcript.yaml `
  -f restore-override.yaml up -d api worker
```

The empty key keeps the rehearsal worker from reaching the provider. Compare the two
stacks before accepting the bundle: Alembic version, `quick_check`, video IDs,
document and passage counts (plus a hash of `document_passages`), users, grants,
conversations, messages, citations, artifacts, feedback, job states, `rag04_chunks`
and the Chroma collection counts. Every value must match, and the restored
`/ready` must report the worker as ready. Then stop the rehearsal stack with
`docker compose -p video-buddy-restore ... down` (the volume is external and stays
until you remove it with `docker volume rm video-buddy-restore_state`).

## 5. Rollback

1. `$C stop worker api`.
2. Retag the previous images: `docker tag video-buddy-runtime:pre-<label> video-buddy-runtime:local`
   (and the web image).
3. Restore the matching bundle into a new volume as in section 4, verify it, then point
   the stack at it, or restore the `tar` archive into an empty `video-buddy_state`.
4. Check out the matching source revision. Code, lockfiles, configuration and the paired
   SQLite/Chroma/media state go back together.
5. `$C up -d api worker`, then run section 2 and one read-only history check in the UI.

Never reset or copy the Gemini usage ledger to regain quota.

## 6. Live checks on the Free Tier

Live probes use the real key and quota. Plan them before running:

- Daily limits from the policy (Pacific-midnight reset, about 15:00 Thai time):
  `gemini-3.5-flash` 20 RPD, `gemini-3.5-flash-lite` 500 RPD, embeddings 1,000 RPD.
- Each model call reserves `countTokens` and `generateContent`. A rate-limited
  primary adds one more admission before the fallback runs. A research run with
  `AGENT_MAX_MODEL_CALLS=6` therefore needs about 13–14 admissions. `--max-calls`
  accepts up to 32. Cases in one probe share the budget.
- Stop the regular worker for the probe (`$C stop worker`), run it with
  `$C run --rm --no-deps ... worker python worker_probe.py --allow-live --workers-stopped ...`,
  then `$C start worker`.

Today's usage per bucket is in `gemini_reservations` (rows with `created_at` after the
current Pacific-day start).

## 7. Evidence

Evidence files stay outside Git in `07_testing_deployment/runtime/release-evidence/`.
Each `main_release.py` check lists file paths relative to that root and their SHA-256.
Record what was measured and its limits (for example "local retrieval only", "fallback
model answered") in the evidence file itself; the gate checks integrity, not meaning.
