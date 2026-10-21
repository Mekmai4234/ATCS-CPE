# Auth integration boundary — pending module 02

The user asked to wait for the auth contract / Google Web Client ID. This branch prepares module 01 UI and an internal interface only. Default production uses `PendingSessionPort`: no Google SDK, no workspace API access and no invented auth endpoints. Do not enable multi-account production or merge as complete authentication.

## Interface versus HTTP contract

`src/session.ts` defines the frontend `SessionPort`. Its methods and fields are not proposed server endpoints. `MemberSession.sessionId` is a non-secret client revision used to replace the workspace; it must never contain the HttpOnly cookie value or an authentication secret. Member, role, status and capabilities must come from a server-verified session. Client validation is defensive rendering, not authorization.

Before replacing `PendingSessionPort`, agree with module 02 on:

- Google credential exchange URL/body, login-CSRF bootstrap/validation, errors, and the public Web Client ID with authorized origins.
- Session restoration response, expiry/revocation semantics and logout invalidation. Use HttpOnly session cookies, Secure on HTTPS, appropriate SameSite and CSRF protection. The client needs no cookie secret.
- CSRF token/header names and renewal for mutations, including logout and admin actions. The `Api` client includes cookies when session security is supplied; it never sends trusted `user_id` or `role` fields.
- Admin capabilities, response schemas and server authorization. No private conversations are requested by AdminView. Demo member controls are explicitly synthetic.
- Normalize admin HTTP failures to `ApiError.status`, including 401 so the session shell discards management content on expiry.
- Per-user ownership of library, jobs/events, conversations, artifacts, caches and idempotency. Shared source lifecycle and authorized retrieval require modules 02–06. Existing module-02 single-user endpoints and CORS settings do not establish those guarantees.
- Reverse proxy / same-origin deployment, SPA route fallback, CSP for GIS, or explicit credentialed CORS with an exact allowed origin. Never use wildcard origins with credentials.

## Browser behavior prepared

Session restore hides all private content. GIS uses the official `initialize` / `renderButton` API; credential is handed directly to the adapter, not browser storage. Closing the Google popup leaves the sign-in button available; the UI provides retry instructions, without claiming a popup-close event was detected. Network/SDK errors expose retry. Suspended or malformed sessions are rejected.

Member workspaces are keyed by member + session revision. Logout unmounts private state and aborts API requests/polling immediately; server logout failure keeps sign-in locked until retry succeeds. HTTP 401 clears the member view, even for non-JSON responses; 403 never automatically resubmits. Returning through browser history cannot resurrect unmounted state; bfcache restore rechecks the session.

## Test limits and remaining acceptance

`tests/session-entry.tsx` uses `/__test__/` paths exclusively. `tests/browser/session.spec.ts` mocks GIS and fixture sessions. Tests cover user/admin UI guards, CSRF propagation, expiry, logout failure, switching A to B and polling cancellation. They do not verify Google signatures, cookies issued by module 02 or server ownership.

The existing backend smoke uses real module-02 HTTP/worker with fixture adapters and the standalone workspace entry. It checks existing import/chat/research/artifact behavior only, bypassing the pending session gate in a development-only harness. Test modes reject deployment builds, and the production bundle contains no test adapter.

Still required: implement the agreed adapter; test first/returning Google sign-in with real accounts; verify cookie/CSRF/CORS against the real server; execute A/B ownership and revocation tests across modules 02–06; accept the complete integration before deployment.

References checked 2026-10-21: [GIS JavaScript API](https://developers.google.com/identity/gsi/web/reference/js-reference), [server token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).
