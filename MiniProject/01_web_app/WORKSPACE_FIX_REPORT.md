# Workspace audit fixes — 29 October 2026

Implemented in modules 01 and 02 after the audit of develop@0912c59.

## Changes

1. **Archive cancellation:** leaving a saved conversation resets archive loading,
   reading mode and errors. Request sequence guards prevent an aborted/older
   response from modifying a newer conversation. Starting a new chat explicitly
   clears archive loading, so both the full composer and Buddy remain usable.
2. **Durable recovery:** the web discovers the current member's pending/paused jobs
   through the authenticated, paginated member-jobs API. Following a recovered job
   uses its existing job ID and GET polling, never another POST. `งานที่ผ่านมา`
   exposes completed jobs and learning artifacts, with pagination. No credential,
   CSRF token or private prompt is written to browser storage.
3. **Multi-tab login:** each challenge receives its own short-lived HttpOnly cookie.
   Another tab or idle challenge renewal cannot overwrite it. Replay, expiry,
   nonce, audience, issuer and CSRF checks are retained.
4. **Real media viewer:** each library card can lazily open `ภาพและ OCR` from the
   real v2 API. It validates the video/generation/evidence and asset IDs, then reads
   image bytes through the authenticated media endpoint. OCR renders as escaped
   text; withdrawn rights and unavailable assets show a retry/error state. Sample
   coverage is explicit. Snapshot metadata is cached only in the current API
   instance and cleared when that session is disposed, avoiding a metadata request
   per image. The UI's legacy chat still uses transcript evidence: this change does
   not claim visual-only AI chat or full-video frame analysis is implemented.
5. **Processing readiness:** workers publish an atomic heartbeat beside their
   SQLite database, isolated by exact database filename. `/health` includes worker
   state; `/ready` returns 503 for missing/stale processing and 200 when ready.
   Pending-work UI warns when the processing worker is unavailable. Worker and API
   must share the data directory. Detection uses a bounded freshness window.

## Verification

| Check                                                       |     Result |
| ----------------------------------------------------------- | ---------: |
| Frontend unit tests                                         | 114 passed |
| Existing browser regression suite                           |  99 passed |
| New archive/recovery/artifact/real-media-path browser cases |   4 passed |
| Actual-checkout isolated auth HTTP + worker/browser suite   |   8 passed |
| Backend suite including new login/recovery/readiness tests  | 143 passed |
| TypeScript + production Vite build                          |     Passed |
| Production authentication-gate smoke                        |     Passed |
| Prettier, scoped Ruff, Git whitespace checks                |     Passed |

Total executed test results: 368 passed. Existing optional live/backend gates are
not counted as passed. New backend tests verify per-member job isolation,
anonymous denial, simultaneous challenges, replay rejection, heartbeat expiry,
idle worker publication and separation of sibling database files. Browser cases
verify the running job is followed without a second POST, completed quiz recovery,
escaped OCR and image removal after authorization is revoked.

Automated tests use isolated fixtures and mocked external Google/provider traffic;
no new paid AI call was submitted for validation. The local application was rebuilt
and API/worker restarted after checking there were no running jobs. Local health
and readiness are checked separately after the restart. Screens and diagnostic
logs remain under ignored runtime directories.
