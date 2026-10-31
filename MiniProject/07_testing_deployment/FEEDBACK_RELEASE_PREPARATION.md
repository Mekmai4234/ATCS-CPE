# Remaining-work preparation — 31 October 2026

This implements 02/07 preparation from the new Remaining Work Plan. It does not
claim completion of 01's mounted UI, 05's producer opt-in, human semantic review or
a production deployment. The user explicitly confirmed: **human-gold is pending**.
04/06 require no source changes. All owned branches merged `origin/develop` at
`372f1369f997f6b281612034ad810eb504edff84` before work.

## Verified baseline and new work

Develop run [41177980439](https://github.com/Mekmai4234/ATCS-CPE/actions/runs/41177980439)
is now completed SUCCESS, all five jobs, for that exact merged develop SHA. This
supersedes the plan's in-progress snapshot, but does not certify the new PR source.

- 02 supplies a typed, opt-in ExecutionContext signal receiver compatible with the
  actual 05 `chat-review-draft-v1` helper. It stages metadata per lease/attempt,
  deduplicates and atomically promotes only the published attempt. No signal text
  enters public chat/job/history/progress; no signal changes publication disposition.
  New metadata uses existing 0004 columns; the deployed migration is untouched.
- `tests/auth/test_answer_signal_contract.py` uses actual 03/04/05/02 services and
  the actual 05 helper and in-memory answer-cache path. Local external model and
  operator-policy fixtures replace remote services. Cache reuses a generation;
  retry discards earlier-attempt metadata; resume binds the exact replacement pair.
  The retry fixture makes the queued synthetic attempt eligible without waiting for
  its backoff; production backoff/quota behavior is unchanged. This fixture mounts
  the hook explicitly and does not pretend the production 05 adapter is mounted.
- Legacy migration drill now writes feedback through the actual API after migration,
  exercises the real `python -m youtube_backend db purge-review` command, retains a
  nonempty 123-token synthetic ledger record and verifies feedback/IDs after paired
  cold restore. Review access remains OFF, including after restore. Rollback-copy
  verification still reopens the original pre-upgrade revision independently.
- Cold backup now includes canonical `media-assets/` namespaces, in addition to
  legacy `media/`. The existing restore test verifies those bytes after removing
  the disposable source. Preserve the logical DATABASE_URL on an actual restore;
  source/media pairing must also pass the selected runtime's checks.
- Optional `compose.feedback.yaml` forwards disabled-by-default review/allowlist/
  retention settings to API and worker. Its explicit maintenance-profile one-shot
  `purge-review` uses the existing state volume, no network and no provider. No
  service or scheduler is started by this change. Compose configuration validates.
- `scripts/feedback_release.py` consumes exact-source operator evidence and a recorded
  five-job CI report. It fails closed for missing UI evidence, old commit/digest,
  failed/missing jobs, expired/undated review and truthy strings. Optional signal
  inclusion requires explicit producer integration evidence. Template values stay
  null; generating one does not attest that a human performed the checks.

## Readiness report commands

From MiniProject, capture the exact reviewed branch CI report privately:

```powershell
gh run view <exact-run-id> --json status,conclusion,headSha,url,jobs | Set-Content -Encoding utf8 07_testing_deployment/runtime/release-ci.json
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/feedback_release.py --checkout --ci-report 07_testing_deployment/runtime/release-ci.json --write-template 07_testing_deployment/runtime/new-review-template.json --output 07_testing_deployment/runtime/feedback-readiness.json
```

The first check is expected to return nonzero until actual UI/privacy/rollout evidence
exists. A merged component, stale CI or this task's fixture tests are not sufficient.
The template is created exclusively and never overwrites an existing attestation.
An operator must supply independently reviewed evidence for the clean final source
using `--evidence`; never fill required checks with true just to pass the gate.

`feedback_release_ready` concerns the declared feedback feature. `human_gold_ready`
uses the existing hash-bound dataset review gate and is independent; it does not
certify actual answers. `live_semantic_acceptance` remains false. Provider access,
auth/TLS and runtime enforcement keep their existing separate gates. The CLI never
migrates a production DB, changes capability, deploys or creates an attestation.

## Operator rollout / rollback

Use `02_api_backend/FEEDBACK_ROLLOUT_RUNBOOK.md`, after 01 has mounted and tested the
real notice/feedback/confirmation/admin UI. Keep general-admin access separate from
the allowlisted content capability and never reset a quota ledger for a test.
The runbook covers stopped paired backup, upgrade head (0004), default-off start,
owned-account smoke, purge verification, scoped allowlist enablement and rollback by
restoring the stopped pair under the old compatible image. Do not downgrade populated
review tables or mix SQLite/Chroma/media from different snapshots.

## Results and limits

Final full backend: **197 passed on Windows host and Linux Docker**. Final full 07:
**133 passed on host and Docker**, all with `-W error`. Real-HTTP browser: **10 passed**,
cleanup passed (`runtime/browser-identity-89a7856acb`). Docker uses read-only current
02/05 source and 07 scripts/tests with explicit PYTHONPATH, no network, non-root and
resource caps. No skip/xfail is introduced. The first synthetic retry test assumed
zero backoff and failed; the fixture now explicitly advances its queued eligibility
without changing production backoff, and the full suites pass.

Focused checks: receiver/privacy/attempt publication 10; actual producer helper/cache/
retry/resume 3; readiness 4; recovery suite 5 and expanded migration drill 1. Compose
configuration was also checked: API/worker review=false, allowlist empty, one-shot
purge command correct and network_mode=none. New exact-source CI is linked in the PR.

Current local synthetic baseline (1,000 pairs, page 20, 40 samples): review HTTP
p50/p95 **32.24/41.55 ms**, idempotent feedback **6.94/9.12 ms**; entire 32-case local
rule batch **0.26/0.27 ms**. Raw ignored `runtime/remaining-work-latency.json` records
source digest `7da1fb72ce2bde1e3767d8e652161a60162b44a957546301246969bd1db964e9`.
These are local measurements, not SLA, model generation/retrieval timing or semantic
acceptance. Provider calls: 0. Readiness check correctly remains blocked without real
UI/privacy/operator evidence and reports human_gold_ready=false; it does not deploy.

Integrated UI E2E/screenshots (full/floating/history/admin, failed save and late old-
session response) remain pending 01's mounting. Source code in 01/03/04/05/06 is not
edited here. New producer calls remain 05's opt-in work; the draft rule signal is
not a confirmed out-of-scope/factual-error verdict. Live answer quality and stage-
specific model latency remain unverified; historical synthetic timings are not SLA
or semantic acceptance. No real account database, provider key, quota ledger or
production capability was changed.
