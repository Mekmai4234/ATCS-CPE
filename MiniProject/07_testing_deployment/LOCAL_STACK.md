# Local transcript-first stack (`video-buddy`)

Runs the full 01–06 system on one machine at `http://localhost:3000`, with the five
`Transcript/` documents baked into the image. This is a **local** profile: plain HTTP on
127.0.0.1 only. Public HTTPS, registered origins and release evidence stay in
[AUTH_DEPLOYMENT.md](AUTH_DEPLOYMENT.md) and `compose.auth.yaml`.

| Service | Image | Role |
|---|---|---|
| `migrate` | `video-buddy-runtime:local` | `transcript_runtime.py migrate`: initialize or upgrade the paired SQLite/Chroma state, then exit |
| `api` | same | FastAPI backend (health on `/health`) |
| `worker` | same | Durable job worker (imports, chat, analysis, research, artifacts) |
| `web` | `video-buddy-web:local` | Caddy serving the built 01 web app and proxying `/api`, `/health`, `/ready` |

Files: [compose.transcript.yaml](compose.transcript.yaml),
[Dockerfile.transcript](Dockerfile.transcript), [Caddyfile.local](Caddyfile.local),
[scripts/transcript_runtime.py](scripts/transcript_runtime.py),
[scripts/image_source.py](scripts/image_source.py).

## Configuration

- **Secrets and per-machine values** come from `MiniProject/.env.local` (start from
  `.env.example`). Required: `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`,
  `ADAPTER_MODE=custom`, `ADAPTER_FACTORY=youtube_answers.team:create_adapters`,
  `BACKEND_FULL_PREFLIGHT=true`, `AUTH_ENABLED=true`, `SESSION_COOKIE_SECURE=false`,
  `WEB_ORIGIN=http://localhost:3000`, `AUTH_TRUSTED_ORIGINS=["http://localhost:3000"]`.
  The compose file overrides container paths (database, Chroma, media, policy).
- **Data** lives in the external Docker volume `video-buddy_state`. Compose never creates
  or deletes it; on a new machine run `docker volume create video-buddy_state` once.
- **Gemini policy** is mounted read-only from `runtime/free-tier-20261026/` at
  `/app/policy/gemini-free-policy.json`.

## Start, update and stop

From `MiniProject`:

```powershell
docker compose -f 07_testing_deployment/compose.transcript.yaml build
docker compose -f 07_testing_deployment/compose.transcript.yaml up -d
```

After a code change, rebuild and recreate only the backend (data is kept):

```powershell
docker compose -f 07_testing_deployment/compose.transcript.yaml build api
docker compose -f 07_testing_deployment/compose.transcript.yaml up -d --force-recreate api worker
```

Check health and that the image matches its recorded source fingerprint:

```powershell
docker ps --filter name=video-buddy
docker exec video-buddy-api-1 python 07_testing_deployment/scripts/image_source.py verify
docker exec video-buddy-api-1 python 07_testing_deployment/scripts/transcript_runtime.py validate
```

`docker compose ... down` stops the stack. Never add `-v`: the volume is external
precisely so application data cannot be removed by Compose.

## Backup and rollback

Before replacing images, tag the current ones and archive the volume while api/worker
are stopped and no job is `queued` or `running`:

```powershell
docker tag video-buddy-runtime:local video-buddy-runtime:pre-<label>
docker compose -f 07_testing_deployment/compose.transcript.yaml stop worker api
docker run --rm -v video-buddy_state:/state:ro -v "${PWD}/runtime/backups:/out" alpine:3 `
  sh -c "tar -C /state -czf /out/video-buddy_state-<label>.tgz . && sha256sum /out/video-buddy_state-<label>.tgz"
```

Roll back by retagging `pre-<label>` as `local`, restoring the archive into the volume
while the stack is stopped, and starting again. Restore code, image and data together.

## Gemini policy renewal (every 7 days)

The broker accepts a policy for at most 7 days after `verified_at`. When it expires every
AI call fails with `free_tier_unverified`, while transcript-document answers keep working.

1. Open Google AI Studio → **Rate Limit** for the same project as `GEMINI_API_KEY`.
   Confirm the tier is still Free and note RPM / TPM / RPD for each model in the policy.
2. Edit `runtime/free-tier-20261026/gemini-free-policy.json` (keep a copy of the old file):
   - `verified_by`: your name; `verified_at`: the time you checked, ISO 8601 with offset
     (e.g. `2026-11-09T19:00:00+07:00`); `expires_at`: at most 7 days later.
   - `pools`: one pool per model bucket with the current `rpm`, `tpm`, `rpd`, `user_rpm`.
   - Do not change `key_sha256` unless the key changed (then re-verify everything).
3. Validate the file before installing:

   ```powershell
   uv run --project 02_api_backend --locked python -c "from youtube_backend.quota import FreePolicy; FreePolicy.model_validate_json(open('runtime/free-tier-20261026/gemini-free-policy.json', encoding='utf-8').read()); print('ok')"
   ```

4. Install the policy fingerprint with workers stopped (usage counters are kept), then
   start api and worker again:

   ```powershell
   docker compose -f 07_testing_deployment/compose.transcript.yaml stop worker api
   docker compose -f 07_testing_deployment/compose.transcript.yaml run --rm --no-deps worker python -m youtube_backend.quota --workers-stopped
   docker compose -f 07_testing_deployment/compose.transcript.yaml up -d api worker
   ```

### Adding or changing a fallback model

`LLM_FALLBACK_MODELS` (in `.env.local`) lists chat/agent models tried in order when
`LLM_MODEL` is rate limited (`quota_wait`, 429) or unavailable (5xx). All calls use the
same key, project and broker; there is no key or account rotation. Embeddings and vision
never fall back. For each model:

1. Confirm it is listed for the key (`models.list`) and has a non-zero Free Tier limit.
2. Make one small `countTokens` + `generateContent` call and record the returned
   `model_version`. It must appear in the model's `returned_models`, otherwise answers
   are rejected as `returned_model_unverified`.
3. Add a pool with its own limits and a `models` entry with `endpoints`
   `["generateContent", "countTokens"]`, `roles` `["chat", "agent"]` and
   `image_capable: false`.
4. Renew and install the policy as above, then recreate api and worker so the new
   environment value is read.

An agent research run keeps the model that produced its first decision, because native
thought signatures belong to that model.

## Diagnosing failures

- `docker logs video-buddy-worker-1 | Select-String job_finished` shows each job's final
  state and sanitized `error_code`.
- Model use per job is recorded in the `gemini_reservations` table (`model`, `endpoint`,
  `role`, `state`). `uncertain` means the request was sent but the provider returned an
  error.
- `context_budget_exceeded` means one request would exceed `MAX_CONTEXT_TOKENS`;
  `free_tier_unverified` means the policy is missing, expired or for another key.
