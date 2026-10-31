# Feedback rollout / rollback runbook — 31 October 2026

**Preparation only.** No production migration/deploy or review capability activation
is performed by these PRs. Develop `372f136` CI run 41177980439 passed all five jobs;
new changes need their own exact-source checks. 01's controls/notice/admin flow are
still unmounted and the user confirmed that human-gold answers are unavailable.

## Before touching the target

1. Pin reviewed backend/worker/frontend commits and image digests. Use the same
   source/configuration snapshot for all three; retain the old release artifacts.
2. Require 07's actual-UI/session/CSRF/capability/failed-save/stale-response evidence,
   five-job CI, reviewed notice/privacy text and backup/restore drill. Passing API
   fixtures or finding a component file does not satisfy mounted-UI acceptance.
3. Declare whether 05 signals are included. If included, its owner must mount the
   opt-in hook in `ANSWER_REVIEW_SIGNALS.md` and test every returned fresh/cache/
   retry/resume path. Draft signals remain unconfirmed metadata, never verdicts.
4. Confirm configured `DATABASE_URL`, `CHROMA_PERSIST_DIR`, `MEDIA_ASSET_DIR`, auth
   origin, secure cookie, Google client ID and quota-policy/evidence paths privately.
   Do not print environment/config containing keys. The Google/Free Tier production
   gates remain independent and must pass; feedback readiness is not provider access.
5. Leave `CHAT_REVIEW_ENABLED=false`, `CHAT_REVIEW_ADMIN_IDS=[]` until the real notice
   and UI are deployed/accepted. Keep retention 1..30 days (default 30).

## Stop, back up and migrate

Freeze new writes at ingress, let authorized pending work finish or cancel it, then
stop ALL API/worker/Chroma clients. Verify no queued/running jobs or committed
deletions remain. An operator flag is an acknowledgement, not an automatic stop.

Use the existing 02 operator CLI with the exact target settings. Example command
shape from MiniProject (replace the backup path with a NEW protected directory):

```powershell
uv run --locked --project 02_api_backend python -m youtube_backend.auth_cli migrate --workers-stopped --backup-dir 'D:/video-buddy-backups/release-unique'
```

This verifies and takes a paired SQLite/Chroma backup (and referenced namespaced
media assets when present), then applies additive Alembic head. For the current
release head is **0004**. It does not recreate the database or clear the quota ledger.
The CLI refuses an existing backup directory; verify `backup.json` and the backup
files before proceeding. Protect backups as private chat data, not public artifacts.

`yk-db upgrade head` is the lower-level migration command when a verified stopped
pair has ALREADY been backed up. Do not edit deployed 0004; future schema changes
require a new migration. Current signal hook reuses existing 0004 metadata columns.

For a canonical full state directory (`app.db`, `chroma/`, optional `media-assets/`
and legacy `media/`), 07's checksum-manifest cold-copy tool is also available:

```powershell
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/recovery.py backup 'D:/explicit-state' 'D:/new-cold-backup' --services-stopped
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/recovery.py restore 'D:/new-cold-backup' 'D:/empty-restore-target'
```

It must not silently omit an externally configured media root: use the 02 paired
backup with actual Settings for such layouts. Preserve the original logical
`DATABASE_URL` and media namespace when switching restored storage; media paths are
bound to the database URL. A scratch directory on disk is not permission to change
the service's logical URL. Validate assets/citations with the selected runtime pair.

## Start with review access off, then smoke-test

Start the API/worker and frontend from the pinned release. Health must report schema
0004; `/ready` must report the intended continuous worker. Auth/Google/HTTPS evidence
must describe the actual deployment. Before allowing review content, verify on
operator-owned test accounts only:

- The same assistant ID in chat 200, job polling and reopened history; persisted
  like/dislike/edit/withdraw across full/floating/history with real CSRF and sessions.
- Warning confirmation bound to exact payload; expired ticket rejects NEW work but
  does not break existing-key replay/replacement. Clear block never invokes provider.
- Withheld draft absent from chat, history, public job progress/citations/logs;
  neutral placeholder has no feedback control. Ordinary insufficiency stays distinct.
- General admin gets 403 on content; only current active allowlisted admin succeeds.
  Exact pair/scope/citations and audited detail/context/review transition are correct.
- Expired case/notes are 404 before sweep, then purged; history erasure removes
  readable copies while existing quota reservations/tokens remain unchanged.
- Failed save and delayed old-account responses do not show false success or another
  account's state. Capture mobile/desktop/keyboard evidence from mounted UI.

Deploy/review the notice BEFORE enabling review content. The 07 optional
`compose.feedback.yaml` forwards disabled-by-default settings to API/worker. Set a
minimal authorized ID allowlist only after all gates pass, then restart both services
to consume configuration. Role/status changes continue to be checked on each read.

## Purge and observation

Continuous `yk-worker` calls the retention sweep every 60 seconds. If it is not
continuously running, schedule `yk-db purge-review` with the SAME target settings;
the one-shot 07 `purge-review` maintenance profile requires no provider/network.
Do not create a scheduler entry against an unverified database path. Test that the
command succeeds against the migrated target and emits counts, never chat text.

Observe job/error/worker health, audit actions and measured latency; the old synthetic
baseline is not an SLA. Record commit/image/config identity, operator, UTC time and
what was actually enabled. Human-gold and live semantic accuracy remain separate
pending work; do not infer them from successful smoke or local rule tests.

## Roll back safely

If ownership/visibility/notice/retention fails, close ingress, set review access off
and restart with the disabled configuration; stop all writers before storage work.
With populated review tables **do not run destructive downgrade**: restore the
verified pre-upgrade pair to a NEW empty target and use the old compatible release.
Keep the failed state separately for authorized investigation; do not overwrite a
live tree or combine SQLite from one backup with Chroma/media from another.

For 02's paired bundle, `backup.json` records the original SQLite/Chroma/media paths.
Restore `app.db` plus `chroma` to their paired locations/mounts and its `media-assets`
contents to the recorded namespace. For 07's canonical bundle, use its restore CLI
and checksum verification. Switch the offline mounts only after path/pair validation.
Reopen the original logical URL under the old image, verify its schema/owned history/
citations/ledger, then restore ingress. An old image must not read new-schema state
and a new image must not be presented as having rolled back to an older schema.
