# Cold recovery procedure

Layout: STATE/app.db and STATE/chroma/. Save image/commit, lockfile, schema versions and
nonsecret model/chunk/index configuration with the release record; store keys separately.
Transcript backups need the same access controls as application data.

1. Stop new work and finish/cancel pending jobs through the API. Stop API, worker and
   ALL Chroma/maintenance clients cleanly. For 07 Compose use
   `docker compose -f 07_testing_deployment/compose.yaml stop api worker`.
2. Make the stopped volume available as a local state directory or run the utility in
   a container with that volume mounted. Do not copy open Chroma files. The flag below
   acknowledges this operator prerequisite; the utility cannot prove no other writer
   exists. Pending jobs cause backup refusal.
3. From MiniProject, for local state:

```powershell
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/recovery.py backup "07_testing_deployment/runtime/state" "07_testing_deployment/runtime/backup-001" --services-stopped
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/recovery.py restore "07_testing_deployment/runtime/backup-001" "07_testing_deployment/runtime/restored-001"
```

4. The utility checks SQLite integrity, copies the pair and verifies SHA-256 before
   restore. Root .env/logs are excluded; nested destinations and symlinks are refused.
   Existing destinations are never overwritten. Retain failed partial output for
   inspection and use another new directory for retry.
5. Keep services stopped while switching BOTH API and worker to the restored pair and
   original embedding/chunk configuration. Run preflight and verify inventory, known
   chunk IDs/times and old citations before accepting new writes. The automated drill
   restores actual synthetic-reference vectors and checks identical results after
   removing its disposable original state.
6. For incompatible schema/index changes, roll back code AND data into a new location
   using the prior known-compatible image/config. Validate before switching; retain the
   original state. Do not use reindex/gc to repair an unknown mismatch; resolve the paired
   configuration first. Preserve all Chroma pair marker files during recovery.

Production-volume restore and image rollback remain operational acceptance work. The
offline drill is not evidence that a production deployment has been recovered.
# Media/Free Tier extension (25 October 2026)

Cold backup format 2 now includes `state/media/` with SQLite/Chroma and checksums.
Restore still accepts format 1. Keep referenced media under this same state tree;
an external media/upload/cache directory is not automatically included. Copy and
validate any external referenced assets as a separate reviewed migration step before
release. Do not run a v2 migration against real data for a test fixture. Quota usage
and policy state must remain in the shared SQLite backup; never reset usage to obtain
more requests. See FREE_TIER_ACCEPTANCE.md for the incomplete integration gates.
