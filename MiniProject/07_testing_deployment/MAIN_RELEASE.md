# Stable release evidence

The 2026-11-02 audit remains **no-go for stable main** until topic/time fallback defects
are fixed by module 05 and verified over API/worker. Module 04 regression of the search
boundary alone does not close either caller defect. Human-gold remains pending.

Use `scripts/main_release.py --checkout --evidence-root <outside-git-directory>
--write-template <new-manifest.json> --output <report.json>` to create an empty acceptance
manifest. The expected nonzero exit means evidence is pending. Fill each check only with
actual evidence files and SHA-256 values, then pass `--manifest` and `--ci-report` exported
by `gh run view <run-id> --json headSha,status,conclusion,jobs`. The gate requires a clean
checkout, matching source revision/fingerprint, five successful CI jobs at that revision,
and hashed evidence for every required acceptance. Public auth/TLS and local model gates
apply only when those capabilities are explicitly selected. It never merges or deploys.
This checks recorded assertions and file integrity, not the truth of human assertions.

Required records include both owner-module defect regressions over HTTP/worker, live
feature success/failure, human-reviewed QA/citation/quiz quality, actual import/embeddings,
measured HTTP capacity/latency, cache/ownership/feedback, recovery on the release source,
and the runbook. Neither this gate nor scripted grading tests establish semantic quality.
Keep synthetic, cache, local-evidence, partial and generated samples distinct. Use the
existing evidence review tool for reviewed gold/timings; do not invent expected intervals,
reviewer identities, p95 from tiny samples or capacity from repository reads.

## Stop, backup, restore and rollback

1. Record source SHA, lock SHA-256 and the reviewed runtime configuration fingerprint;
   exclude credential values. Stop new submissions and drain current jobs, or cancel
   explicitly and retain ledger/uncertain usage. Stop API, worker and every Chroma client.
2. Use `scripts/recovery.py backup <state> <new-bundle> --services-stopped` with
   `--media-source <actual-media-root> --database-url <actual-sqlite-url>` when media lives
   outside the state tree. Keep reviewed configuration and compatible image digest with
   the checksummed bundle, separately from secrets. Never back up an active SQLite/Chroma pair.
3. Restore to a new destination, never over live data: `scripts/recovery.py restore
   <bundle> <new-state> --database-url <new-sqlite-url>`. The URL is required for media
   namespace relocation. Verify nonempty media bytes, source versions, inventories,
   citations and ownership before switching any service configuration.
4. Start the same reviewed API/worker configuration, then verify worker-ready and a
   bounded read-only/history journey. Health alone is insufficient for provider/quality.
5. If acceptance fails, stop/drain again; restore the compatible **code, lock, config and
   paired SQLite/Chroma/media bundle together**. Preserve usage accounting; never copy
   or reset a provider ledger to obtain another dispatch allowance. Verify before restart.

Reuse the existing cold-restore, relocation, checksum and ownership regression suites.
Re-run them for a changed release source/config; retain earlier results as historical
evidence. Public deployment, model enablement, production data switches and main merge
are separate release actions and are not performed by these checks.
