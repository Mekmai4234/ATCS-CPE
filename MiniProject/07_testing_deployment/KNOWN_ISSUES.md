# Regression safeguards and remaining dependencies

The 19 October failures in TEST_REPORT.md are historical. Develop has since merged
03's bounded cleanup and 04's store/configuration safeguards. Current 07 gates check
behavior through supported interfaces rather than mock removed module attributes.

| ID | Current gate |
|---|---|
| K03-PIPE | Real 20 MiB child output, production 8 MiB ceiling; bounded completion and child reap. |
| K04-ENV | Selected FullSettings snapshot exported to runtime and the actual maintenance resolver; stale module dotenv values cannot override it. |
| K04-STORE | Wrong-store reindex and GC must raise index_store_mismatch before changing active/runs/chunks metadata or creating the wrong directory. |

No xfail/skips mask these checks. Current measured results and exact base/overlay refs
are in REVIEW_FIX_REPORT.md. PR13 removes 05's old ENV_FILES constant; preflight now
uses FullSettings and the new loader when available, with an exported legacy-loader
compatibility check on develop. PR16 updates 02 full tests for that new 05 interface.
The 07 PR does not merge pending PR11/13/16 implementation changes.

Remaining dependencies: active CI still needs a repository-root workflow outside 07;
frontend checks await integration of 01 (PR15 is separate). Live semantic review,
production hosting/restore/rollback and browser acceptance remain separate gates.
Offline and isolated startup checks do not establish provider availability or AI quality.
