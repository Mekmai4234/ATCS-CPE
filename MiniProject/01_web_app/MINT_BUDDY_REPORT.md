# Module 01 — mint UI and Floating Buddy

Date: 24 October 2026. Input: the supplied `00_overview.md` and `01_web_app.md`, plus all three images under `D:\Web\New folder`. Base checkout: `0745d27` (module-01 branch already synchronized with develop). Only module 01 changed; no backend/domain modules, migrations, provider configuration or secrets changed.

## Delivered

- **01A / mint UI:** replaced the rendered forest with a CSS mint canvas, dark green reading text, emerald buttons, coral accents and the existing fonts. Updated Login/Home/library/reading/Admin surfaces and added home learning shortcuts. Demo stays labelled and no reference-picture profile, views, lessons or AI responses are presented as real data. Terms/privacy/help links open substantive public pages.
- **01A / authentication:** reused HttpSessionPort, GIS and the nonce/cookie/CSRF flow. No duplicate auth client or password signup. Safe internal destination restore after login; ordinary users cannot redirect into an admin session. Existing session-expiry/suspension/network handling remains. Popup-close/block instructions provide retry without claiming a signal the GIS button API does not expose.
- **01B / mascot:** three independent generated transparent raster layers, code pupils, bounded head/eye transforms, finite wave/greeting/success states and the existing still fallback. Nearby pointer tracking uses refs/requestAnimationFrame; hidden tabs and reduced motion reset it. Head-only launcher rigs do not register tracking listeners. There is no WebGL, audio or motion-sensor permission. [Source/optimized assets, calibration and final prompts](design/buddy-rig/README.md).
- **01B / launcher:** 72 px head button with real pointer capture, 7 px drag threshold, drag/click separation, cancel rollback and visualViewport clamping on resize/keyboard changes. Keyboard corner presets/reset, hide and navigation restore are available. Only versioned `{v,x,y}` coordinates are saved; corrupt/unavailable storage falls back safely.
- **01C / shared chat:** FloatingBuddy consumes App's existing Api, draft, ready-video selection, turns, scope and conversation. It does not create an independent conversation store. Minimize/reopen/full-page chat continue the same conversation. Changed effective scope sends a null conversation ID and announces a new conversation. Each turn identifies its source clips.
- **01C / result lifecycle:** Enter/Shift+Enter/IME handling, 200 or accepted/polling jobs, partial/error/cancel/retry, timestamp citations, unavailable-source handling and source-generation safeguards are retained. Suggestions only populate the draft. Explicit history retrieval paginates the existing authorized conversation endpoint and merges by job ID without undoing citation invalidation.
- **01C / accessibility:** desktop dialog is non-modal; mobile sheet uses background inertness, focus containment and Escape/minimize focus return. Readers can stay on old messages and opt into new ones. Logout/account changes unmount messages, selected sources, conversation and polling, including the portal.

## Verification

| Check                                                      | Result                                                                                                               |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Frozen-lockfile installation                               | Passed; no new dependency                                                                                            |
| Unit suite                                                 | 85 passed across 6 files                                                                                             |
| Browser suite                                              | 64 passed; 8 integration-only cases skipped in this command                                                          |
| Auth-enabled HTTP + worker, `identity_smoke.py --checkout` | 7 passed separately using the actual checkout backend source and an isolated DB                                      |
| TypeScript / production build / format                     | Passed                                                                                                               |
| Production preview smoke                                   | Real session/challenge requests; unavailable auth keeps private routes gated, no demo selector or workspace requests |

The 17 new Buddy browser cases cover public/private boundaries, drag/cancel/tap/keyboard/corners/reset/hide/restore, saved/blocked storage, shared full/floating conversation and history, scope changes, no automatic suggestion submission, 202 cancellation, IME, bounded/reduced motion, still fallback, no forced scroll, touch/keyboard-sized viewport, zoom-equivalent layout and four screenshot widths. Axe checks cover both the existing reading surface and the floating dialog; the new emerald color was darkened to pass active-button contrast.

The actual-checkout HTTP case drives the normal frontend entry through sign-in, import, selected scope, floating question/citation, authorized history, full-page follow-up, changed-scope conversation reset, logout and another member's empty chat. Other HTTP cases retain nonce/revocation/CSRF/roles/private-resource/shared-source coverage. Only external Google verification/GIS and provider content are fixtures; backend auth/session/ownership routes and worker are real.

## Visual evidence

| Width | Login                                         | Home                                        | Floating chat                               |
| ----- | --------------------------------------------- | ------------------------------------------- | ------------------------------------------- |
| 375   | [Login](docs/screenshots/mint-login-375.png)  | [Home](docs/screenshots/mint-home-375.png)  | [Chat](docs/screenshots/mint-chat-375.png)  |
| 768   | [Login](docs/screenshots/mint-login-768.png)  | [Home](docs/screenshots/mint-home-768.png)  | [Chat](docs/screenshots/mint-chat-768.png)  |
| 1024  | [Login](docs/screenshots/mint-login-1024.png) | [Home](docs/screenshots/mint-home-1024.png) | [Chat](docs/screenshots/mint-chat-1024.png) |
| 1440  | [Login](docs/screenshots/mint-login-1440.png) | [Home](docs/screenshots/mint-home-1440.png) | [Chat](docs/screenshots/mint-chat-1440.png) |

States: [queued/loading](docs/screenshots/mint-chat-loading.png), [cancelled/error outcome](docs/screenshots/mint-chat-cancelled.png), [Google SDK network error](docs/screenshots/mint-login-network-error.png). These screenshots show clearly labelled synthetic demo/fixture sessions, not production or real-Google acceptance. Existing screenshots remain historical.

## Limits and handoff

- The backend has GET history for a known conversation but no account-wide conversation-list endpoint. This change does not invent one or persist private conversation IDs in localStorage. A full reload starts a clean client workspace and restores membership from the server.
- The Admin console retains its existing restricted capabilities. Buddy is available in the member workspace; an admin returns there to chat with their own authorized library, not with other members' clips.
- The mascot is a layered rendered rig, with a fixed tablet-holding hand and independently waving arm; it is not a fully rotatable 3D model.
- The 200% layout check uses a 720 CSS-pixel viewport at 2x device scale, equivalent to a 1440-pixel surface at 200%; it is not a claim of manually testing every native browser zoom or mobile OS keyboard.
- No real Google account/new-returning consent test, live Gemini/YouTube answer-quality run, public deployment or combined 02–07 release certification was performed. Actual-checkout HTTP tests use a replacement external verifier, not Google signatures. Keep Draft until the real-Google/deployment gates are accepted. Nothing was merged or deployed by this task.
