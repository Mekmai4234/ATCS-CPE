# Regression safeguards and remaining dependencies

The 19 October failures in TEST_REPORT.md are historical. Develop has since merged
03's bounded cleanup and 04's store/configuration safeguards. Current 07 gates check
behavior through supported interfaces rather than mock removed module attributes.

| ID | Current gate |
|---|---|
| K03-PIPE | Real 20 MiB child output, production 8 MiB ceiling; bounded completion and child reap. |
| K04-ENV | Selected FullSettings snapshot exported to runtime and the actual maintenance resolver; stale module dotenv values cannot override it. |
| K04-STORE | Wrong-store reindex and GC must raise index_store_mismatch before changing active/runs/chunks metadata or creating the wrong directory. |

No xfail/skips mask these checks. REVIEW_FIX_REPORT.md retains historical candidate
results; its pending-PR descriptions are not current integration blockers. The merged
factory uses resolved backend configuration rather than 05's removed ENV_FILES constant.

As of develop d06321e (1 November 2026), repository-root CI and module 01 integration
exist. Develop run 41309549549 completed successfully on Linux and Windows, together
with frontend, packaging and local-media-tools. A later release must verify its own
exact source; this result does not certify future commits.

Remaining release evidence includes real-provider feature/quality review, measured
capacity and paired operational recovery. Public Google/origin/TLS acceptance applies
when deploying publicly. Offline and isolated startup checks do not establish provider
availability or AI quality; a localhost release does not require public hosting.
