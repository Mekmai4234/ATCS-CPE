# Auth integration — module 02 PR18

Updated 2026-10-22. Default production now uses HttpSessionPort. Contract inspected/tested from origin/codex/02-google-auth-ownership@b047e809f983ffb2e4f3f9d3e3f074b8976cd6da. This dependency remains separate from develop; module 01 changed no backend files or consumer locks.

## HTTP mapping

| Operation   | Real contract                                          | Frontend                                                                              |
| ----------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| Restore     | GET /api/auth/me → user, csrf_token                    | Cookies; 401 guest, other errors visible                                              |
| Challenge   | GET /api/auth/challenge → nonce, csrf_token, client_id | Server nonce/Client ID passed to GIS initialize                                       |
| Exchange    | POST /api/auth/google with credential, csrf_token      | Login cookie included; local challenge consumed once                                  |
| Logout      | POST /api/auth/logout, X-CSRF-Token                    | Private UI/polling cleared immediately; failure locks sign-in; 401 already signed out |
| Admin stats | GET /api/admin/stats                                   | Actual users and queued/running counts                                                |
| Members     | GET /api/admin/users?q=&limit=50&offset=               | Server search/pagination                                                              |
| Update      | POST /api/admin/users/{user_id}, role or status        | Cookie + session CSRF; server protects last admin and revokes target sessions         |

Real admin sessions advertise only overview/members. No audit/global video/global job list endpoint exists in this contract: those menus are hidden, not filled with fake empty data. Demo sections remain explicitly synthetic. No private conversations are requested by AdminView.

user_id maps to member.id; null name/email use display fallbacks. sessionId is a random client revision, never a cookie value or secret. Member/role/status come from server-verified responses. Backend remains the authority.

## Nonce lifecycle

Server challenges last 300 seconds. Exchange is conservatively limited to 240 seconds; the idle Google button refreshes after 230 seconds. Failed/uncertain exchange consumes the local challenge and remounts with a fresh one. Old-button callbacks are ignored. SDK/network failures offer manual retry, never automatic token/mutation resubmission. Closing a popup leaves retry instructions; the UI does not claim a popup-close signal.

## Configuration / same-origin deployment

VITE_DEMO_MODE=false uses the real adapter. VITE_API_SAME_ORIGIN=true is the default: browser requests relative /api, and Vite development proxies to NEXT_PUBLIC_API_BASE_URL (default http://localhost:8000). Production must supply an equivalent /api reverse proxy and SPA fallback for frontend routes. Unknown /api routes must not return index.html.

Configure module 02 GOOGLE_CLIENT_ID, AUTH_ENABLED, the exact trusted frontend origin and appropriate cookies. Production requires HTTPS/Secure HttpOnly cookies and Google authorized origins. The server challenge supplies the authoritative public Client ID; VITE_GOOGLE_CLIENT_ID is only a legacy/test adapter fallback. No Google secret belongs in frontend configuration.

Testing exposed unreadable cross-origin 401 responses in the inspected backend. Same-origin proxying preserves readable authentication failures and host-only cookie behavior without editing module 02. VITE_API_SAME_ORIGIN=false uses an absolute browser API URL and requires explicit cookie/CORS validation for all success/error responses. Vite preview does not proxy backend requests; preview real auth behind the deployment reverse proxy.

## Evidence / remaining acceptance

python tests/identity_smoke.py --ref origin/codex/02-google-auth-ownership extracts module 02 into ignored runtime, creates a new DB and starts real auth-enabled HTTP + worker. A loopback-only test server replaces only the external Google verifier. The normal frontend entry and real nonce/CSRF/session/role/ownership routes execute without browser API mocks. GIS and provider data are synthetic. Loopback tests deliberately use non-Secure HTTP cookies; production HTTPS cookie behavior is not established by them.

Still required: real Google new/returning account sign-in with authorized origins, full 03–06 integration/locks, and module-07 deployment acceptance. Keep the PR Draft until release gates pass. AUTH_REVIEW_REPORT.md records exact evidence. Historical /**test**/ session and standalone workspace tests remain separate regression harnesses excluded from deployment builds.

Reference checked 2026-10-22: [GIS initialize nonce](https://developers.google.com/identity/gsi/web/reference/js-reference#nonce).
