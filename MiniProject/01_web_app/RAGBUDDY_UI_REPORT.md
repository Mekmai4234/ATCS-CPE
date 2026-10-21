# RAG Buddy UI review — 21 October 2026

Branch: `feature/01_ragbuddy_google_ui`; base: `origin/develop@69f5347` (PR #15 merged). Scope: module 01 only. No database migration or backend endpoint changes.

## Implemented

- Forest/mint/coral design tokens and responsive navigation, white reading surfaces, a separate forest background and transparent 3D-style RAG Buddy WebP variants. Based on the user's `D:\Web` reference images; no screenshot replaces interactive UI. See [asset provenance](ASSETS.md).
- Unified login page with session checking, Google SDK network retry, suspended/expired states and no password fields. The official GIS button component is prepared; production login remains unavailable while waiting for module 02.
- User home hero with YouTube URL import, library/chat shortcuts and profile/logout. Existing library, chat, analysis, research, learning, partial results, cancellation, pagination and source-generation citation rules are retained.
- Internal SessionPort and account/session-keyed workspace. Disposal aborts requests and polling. Logout failure stays locked until retry succeeds. 401 clears private views, including non-JSON failures; 403 does not auto-resubmit. Session mutations require a negotiated CSRF header and credentials; the client adds no trusted ownership fields.
- Capability-driven admin UI with no private conversation view. Synthetic demo accounts support member search, suspend/reactivate and audit entries. Real admin data/actions remain pending API support; no production admin menus are exposed by default.
- Test-only entry points are isolated from the production build, and test-mode builds are rejected. Explicit DEMO mode has synthetic A/B/admin accounts and is clearly labelled.

## Verification

All checks below passed locally on Windows with installed Google Chrome:

| Check                                                | Result                                                                               |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `pnpm install --frozen-lockfile`                     | Passed                                                                               |
| `pnpm typecheck`, `pnpm build`                       | Passed                                                                               |
| `pnpm format:check`                                  | Passed                                                                               |
| `pnpm test`                                          | 57 passed across 4 files                                                             |
| `pnpm test:browser`                                  | 47 passed; 1 backend-only case intentionally skipped                                 |
| `python tests/backend_smoke.py --ref origin/develop` | Separate backend case passed using module-02 HTTP + worker and fixture adapters      |
| `pnpm test:production` after the default build       | `/`, `/admin`, `/chat` stay gated; no demo selector, GIS or workspace API requests   |
| `vite build --mode session-tests`                    | Rejected as expected; no test adapter paths found in production bundle               |
| Axe WCAG A/AA checks on the chat reading surface     | No detected violations in the tested fixture; not a full accessibility certification |

The 17 session browser cases include pending-auth route guards, mock GIS credential exchange without browser persistence, direct admin denial, capabilities, A logout → B login/history, polling cancellation, workspace/admin 401, 403/CSRF/no resubmit, suspended account, logout failure, slow session restore, SDK network failure, three viewport layouts and keyboard/contrast checks.

The existing source lifecycle regression cases still pass: deleting a source disables old citations, reimport does not revive them, refresh checks historical identity, and late answers cannot restore deleted-source links. Backend smoke covers import, chat, compare, research and saved artifacts using synthetic adapters; it does not call paid providers or test live retrieval quality.

## Visual evidence

| Viewport | Login                                                     | User home                                               |
| -------- | --------------------------------------------------------- | ------------------------------------------------------- |
| 375 px   | [Mobile login](docs/screenshots/ragbuddy-login-375.png)   | [Mobile home](docs/screenshots/ragbuddy-home-375.png)   |
| 768 px   | [Tablet login](docs/screenshots/ragbuddy-login-768.png)   | [Tablet home](docs/screenshots/ragbuddy-home-768.png)   |
| 1440 px  | [Desktop login](docs/screenshots/ragbuddy-login-1440.png) | [Desktop home](docs/screenshots/ragbuddy-home-1440.png) |

Screenshots show explicitly labelled DEMO mode. Compared visually with the reference composition: forest background, mint mascot, coral accent, split login and white controls. The reference password/register forms are omitted to meet the Google-only requirement. Horizontal viewport fit is asserted at all three sizes. Long reading areas use quieter card surfaces; reduced motion rules are preserved.

## Pending — Draft PR

The user asked to wait for module-02 auth details. No real auth/admin endpoint names were assumed. Google Client ID configuration alone does not enable login; `PendingSessionPort` stays closed. Mock GIS tests are not real Google first/returning sign-in, and demo account separation does not prove server authorization.

Before production or a complete-auth merge: agree the auth/CSRF/admin contract, implement the real adapter, verify session cookie security and real Google login, and run integrated A/B ownership tests across modules 02–06. Existing backend single-user endpoints are not protected by this frontend gate. See [AUTH_INTEGRATION.md](AUTH_INTEGRATION.md) for the concrete handoff. Prior TEST_REPORT.md / FOLLOWUP_REPORT.md remain historical reports for earlier PRs.
