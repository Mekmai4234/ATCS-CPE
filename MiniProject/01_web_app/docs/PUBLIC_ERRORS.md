# Public AI service errors

Module: 01_web_app. Updated 26 October 2026.

## User-facing behavior

Configuration verification failures now display:

> ขณะนี้ผู้ช่วย AI ยังไม่พร้อมให้บริการ กรุณาลองใหม่ภายหลัง

The same public message is used for HTTP errors, failed jobs, paused jobs, full chat and floating Buddy chat. Provider names, Free Tier/project/model verification details, HTTP status numbers, raw failure codes and appended request IDs are excluded from this service-error copy. Other failures use understandable messages for a busy service, a temporary outage, connection failure or a video index that is not ready.

Failed jobs still finish as failures, paused work remains paused and existing-job follow-up uses GET. No successful answer is fabricated and no new automatic POST retry is added. Explicit retry times remain distinct from estimates.

## Diagnostics and current local cause

The underlying ApiError fields and durable job error_code retain their diagnostic information. This is a UI presentation change, not an API authorization or logging change.

The local server was checked read-only: a failed job has free_tier_unverified and the configured runtime has no operator policy file. This UI fix does not certify Free Tier, configure a policy, switch models or bypass the backend broker. Service enablement still requires the appropriate server/operator setup.

## Validation

- 109 unit tests passed.
- 27 targeted browser tests passed, including direct HTTP, failed-job and paused-job configuration errors in both chat views.
- The tests assert that private diagnostic text is absent, no successful turn is rendered, the composer becomes usable again, and the request is not automatically resubmitted.
- Formatting, TypeScript/production build and production login-gate smoke passed.
- Tests used isolated fixtures and made no Gemini calls.
