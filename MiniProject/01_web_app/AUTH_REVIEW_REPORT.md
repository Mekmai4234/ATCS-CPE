# Module 01 review fixes — 22 October 2026

Reviewed all supplied documents: `00_summary.md`, `01_review_and_fixes.md`, `08_verification.md`, `09_system_progress.md`. Only module 01 files changed. No edits to modules 02–07, databases, consumer locks, deployments or other PRs.

This updates existing Draft PR #17 (`feature/01_ragbuddy_google_ui`) from the previous UI scaffold at b2319f7. Backend contract/test dependency: PR18 `origin/codex/02-google-auth-ownership@b047e809f983ffb2e4f3f9d3e3f074b8976cd6da` (newer than the review document's f406d32 snapshot).

## Review items addressed

1. Replaced default PendingSessionPort with HttpSessionPort. GET me, nonce challenge, Google credential exchange, session cookies, session CSRF and logout use actual module-02 routes. Null profiles have display fallbacks; client revision is random and unrelated to the session-cookie secret.
2. GIS initialize now receives the server nonce and Client ID. Challenges are single-use locally, refreshed after failed delivery and before idle expiry; callbacks from old buttons are ignored. No credential or session secret is persisted in browser storage.
3. Real admin mapping uses stats and paginated/searchable users, plus server role/status updates. Counts come from stats rather than page length. Only overview/members are exposed: PR18 currently has no audit/global-video/global-job listing endpoint. Unsupported data is absent, not fabricated as empty lists.
4. Private workspace cleanup, 401 handling and no automatic 403 resubmission remain intact. Admin 401/403 drops management content. Server revocation/last-admin guards are exercised by browser tests. Logout treats an already revoked server session as signed out but retains the lock/retry behavior on network/server errors.
5. Browser/backend acceptance now uses the normal frontend entry and actual auth-enabled module-02 HTTP/worker. Only the external Google verifier/GIS and provider data are fixtures. Added same-origin development proxy and documented production reverse-proxy requirements after observing unreadable cross-origin 401 responses. No backend CORS changes were made.
6. Updated env.txt, step.txt and process.txt in English, auth contract/runbook, production smoke and review evidence. Demo URL parsing now accepts relative /api paths; deletion copy describes removal from the current account's library. Completed `detach` jobs now display their real status. A client-only library revision separates historical evidence from fresh answers after reattaching the same shared physical source; it is never sent as an authorization claim.

## Verification

| Check                                   | Result                                                                                                                               |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Frozen-lockfile dependency install      | Passed                                                                                                                               |
| Unit suite                              | 69 passed in 5 files                                                                                                                 |
| Normal browser regression suite         | 47 passed; 7 integration-only cases intentionally skipped and run separately                                                         |
| Auth-enabled browser + HTTP + worker    | 6 passed using external-verifier/provider fixtures                                                                                   |
| Legacy backend HTTP + worker regression | 1 passed separately against develop@69f5347                                                                                          |
| TypeScript, production build, format    | Passed                                                                                                                               |
| Production preview smoke                | Real HttpSessionPort requests me/challenge; unavailable auth keeps /, /admin, /chat private; no demo selector/GIS/workspace requests |

The six real-HTTP cases cover new/returning synthetic identity and nullable profile; HttpOnly SameSite cookie issuance; nonce rejection and fresh retry; idle nonce refresh and stale callback rejection; A logout → B login/history with private job/conversation/artifact/transcript denial; Admin stats/search, promotion/demotion, revocation, CSRF, suspension/reactivation and last-admin protection; shared-source withdrawal preserving the other member while old UI citations stay disabled and fresh answers have valid citations after reimport of the same physical generation.

Existing source-generation, cancellation, partial results, safe citations, artifacts and responsive/keyboard/contrast regressions remain covered. Normal browser tests deliberately skip the six identity cases and one legacy backend case, rather than count mocked tests as real backend integration. Fixture mode does not establish YouTube/Gemini retrieval or answer quality.

## Evidence and remaining gates

The isolated runners write backend SHA, mode, verifier type and browser exit status to ignored runtime reports, along with logs. [Admin member screen](docs/screenshots/identity-members.png) uses real backend fixture users; this is not real-Google or deployed production evidence. Prior UI screenshots and reports remain historical.

No usable Google Web Client ID / interactive real account test was provided during this run. Real Google first/returning login, authorized origins and production HTTPS/Secure-cookie behavior therefore remain unverified. Full 03–06 ownership integration, combined consumer locks, deployment/migration/restore acceptance and module-07 release gates remain outside this module-only change. PR #17 stays Draft, is not merged, and does not claim the member release is ready for deployment. See [AUTH_INTEGRATION.md](AUTH_INTEGRATION.md).
