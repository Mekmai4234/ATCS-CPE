# Follow-up corrections — 30 October 2026

All four findings from the follow-up audit have been addressed.

1. **Video scope and history (05):** current question and history now have separate fields. Timestamp selection, identity guards and counting guards inspect the current question only. History remains available to the model as untrusted reference context. History-sensitive cache keys use the new structured representation so previously history-clipped answers are not reused for that representation.
2. **Full learning evidence (02/06):** learning resolves complete observations through the authorized backend store. Display titles remain short, but are never the factual input. Observation kind and canonical evidence IDs are preserved. If input budgets require fewer observations, whole observations are selected and partial selection is disclosed; individual factual text is not cut midway.
3. **Immutable evidence and cache (02):** each reconciled inference publishes an immutable revision. A separate expiring lookup points to the newest revision. Refreshing a cached answer does not overwrite earlier observations. Existing legacy cache rows and citations remain readable. No database migration, ledger reset or source re-import is required.
4. **Worker readiness (02):** API inline execution has liveness reporting disabled. Dedicated workers continue publishing their heartbeat. A successful inline chat no longer makes readiness claim that a background worker exists. Stopped-worker detection still has the normal configured heartbeat expiry window.

## Verification

- Backend full suite: 147 cases pass. An old test that treated the API's inline worker as a daemon was corrected to construct the dedicated worker. The full suite was then rerun successfully.
- Answer module full suite: 212 cases pass, including history containing an old timestamp/identity question, current explicit timestamps and out-of-window rejection.
- Learning full suite: 128 cases pass. Full-text/qualification preservation and canonical evidence input were additionally checked after the final prompt-input cleanup.
- Isolated checkout identity/browser smoke: 8 cases pass against the actual backend implementation with a test identity provider.
- Total: **495 distinct passing cases** for this correction round. Repeated targeted runs are not counted again.
- Scoped Ruff and committed-diff checks pass. Production source changes were committed on the relevant module branches and integrated into `develop`.

Regression checks cover both old and new citations after regenerated evidence, legacy-row reads, qualifications beyond the 160-character display title, and successful HTTP chat while `/ready` correctly remains 503 without a daemon.

No real Gemini inference was needed for these regressions; they do not consume model quota or certify new live model answer quality. The separate live visual-learning verification limitation recorded in [the previous report](VIDEO_ANSWERS_REPORT.md) remains applicable.

Ignored execution logs are `runtime/four-fixes-backend-final.log`, `runtime/four-fixes-answers.log`, `runtime/four-fixes-learning.log` and `runtime/four-fixes-identity.log`.
