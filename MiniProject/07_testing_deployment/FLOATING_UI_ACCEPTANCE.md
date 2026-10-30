# Historical UI acceptance matrix — superseded integration status

The legacy/absent-UI observations below describe the earlier review checkout.
See [INTEGRATED_SYSTEM.md](INTEGRATED_SYSTEM.md) for the current combined implementation,
bound floating test config, runtime evidence and remaining external acceptance.
Do not interpret the historical BLOCKED rows as a fresh test result.

# Floating Buddy / mint UI acceptance — 24 October 2026

This is a release matrix, not a declaration that module 01 has implemented these
features. Default checkout at this review has the legacy workspace. PR17 still has
the prior forest UI, without the new draggable launcher/layered mascot. No 01 source
was edited by 07. The supplied mint/chat/login PNGs are design references only.

## Commands and evidence classes

From MiniProject, first run the source-record/locked regression commands in README.
Install/build module 01 with its frozen pnpm lock and Chromium. Then:

```powershell
node 07_testing_deployment/scripts/ui_qa.mjs
# Strict surface gate: returns nonzero while acceptance is blocked.
node 07_testing_deployment/scripts/ui_qa.mjs --require-floating
Set-Location 01_web_app
pnpm exec playwright test --config ../07_testing_deployment/playwright.floating.config.ts
```

`ui_qa.mjs` captures current Home/Chat/Login routes at 375/768/1024/1440 CSS px,
plus interaction traces and actual built JS/CSS gzip/image/font sizes. It explicitly
uses local fixtures and blocks external browser requests. `accepted` stays false:
capture/trace production alone is not a design, auth or performance acceptance result.
The default CI summary displays that blocker. It does not fetch an older frontend.

The four strict interaction cases are provisional acceptance contracts. Their accessible
names must be bound to the delivered 01 interface before product acceptance: button
named "เปิดแชต Buddy" (or the documented bilingual equivalents), named chat dialog,
minimize control and position/reset alternative. An absent launcher fails immediately
with BLOCKED; cases never skip to green. Current checkout fails all four at that entry
gate, so later test bodies are **not validated** against an implementation.

The fixtures in this suite do not establish real API/model invocation counts. Real
account-switch/slow-result/no-duplicate-request acceptance must additionally use
`browser_identity.py --checkout` with the actual frontend harness and real API/worker.
Synthetic composition events are not an OS IME certification.

## Required matrix / current state

| Area | Acceptance probes | Current evidence/state |
| --- | --- | --- |
| Source selection | Change marker after pin; run changed checkout; reject old digest and mid-run edits; reject pinned fallback in default workflow | Automated source regressions; default CI uses direct checkout |
| Google entry | /login signup/signin, no password/admin signup, first/returning user, popup cancellation/load errors/suspension | BLOCKED on current 01; backend auth suite passes separately; real Google pending registered staging |
| Private routes | Guest direct URL/API; user denied admin; admin denied private clips | Backend negatives pass; current UI entry still legacy, frontend gate not accepted |
| Drag/click | Click/minimize/focus restoration; below/above declared threshold; drag must not click | Provisional strict case; entry BLOCKED. Bind threshold boundary to delivered 01 value (24px probe is not an exact threshold claim) |
| Containment/capture | Four corners/edges, release outside handle, pointercancel, resize/rotation, no stuck dragging | Provisional strict case; entry BLOCKED; real touch/device cancellation pending |
| Non-drag alternative | Mouse/touch/keyboard, move-to-corner/reset, full 44x44 hit target | Strict keyboard/position case proposed; entry BLOCKED; do not require dragging as the only input |
| Persistence | Blocked/quota storage, malformed/stale/NaN/huge coordinates, clamp on viewport change | Blocked-storage strict case proposed; corrupt-coordinate cases pending binding to actual key. Store coordinates only, never session/history |
| Panel/mobile | Flip at desktop edges; visualViewport/real keyboard; visible composer/send; modal focus trap and focus restoration; avoid covering focused controls | BLOCKED; needs actual mobile/keyboard device validation, not viewport resize alone |
| Chat flow | Ready-video scope, 200/202, pending/failure/partial/cancel/retry/401, safe timestamp, history/new chat, detached source | Legacy browser/domain regressions pass; repeat via floating UI and real HTTP after implementation |
| State/privacy | A minimizes chat, logout, B sees no A scope/history/result; delayed results/back; changing scope cannot relabel old answer; reopen cannot resubmit | Backend/private ID tests pass; FLOATING flow BLOCKED, requires real-adapter request assertions |
| Input/rendering | IME composition, Shift+Enter, HTML/script/unsafe Markdown URL, long Thai, one chip click = one job, no speculative model calls | Legacy rendering regressions available; synthetic composer test blocked; real IME/model count/unsafe content through new UI pending |
| Visual | Compare mint references at 4 widths; login/home/chat/library/learning; 200% zoom, long Thai, empty library, loading/error/missing thumbnail | 12 legacy fixture screenshots captured; no Home horizontal overflow observed. New reference acceptance NOT granted |
| Mascot | Bounded pointer/head/eyes, pointerleave center, no full-page rerender per move, no CLS | BLOCKED; layered asset/rig and implementation absent |
| Motion/lifecycle | Reduced motion disables unnecessary idle/follow; hidden tab/unmount removes listeners/RAF; asset failure fallback preserves CTA/login/chat | Capture uses reduced-motion preference only; behavior/lifecycle/fallback acceptance BLOCKED |
| Accessibility | Normal text contrast target >=4.5:1; visible focus/control contrast; 44x44 important targets; no hover-only controls | Targets from the brief; no contrast or touch-target certification of absent new UI |
| Performance | Agreed device/network profile; resource budgets, pointer/composer interaction trace, CPU/CLS and rerender measurements | Current bundles/traces recorded with machine/browser details. No agreed representative profile/budget and no 60fps claim |
| Deployment | Actual-source frozen locks, production factory/HTTPS/cookie/CSRF, no secrets in bundle/storage/logs | Locked/container checks run on current source. Real Google/public HTTPS/browser secure-session acceptance remains pending |

QA guidance was checked with the local ui-ux-pro-max "dragging movements" and "focus
not obscured" queries: provide an alternative to dragging and keep focused controls
visible. Full-focus visibility is a product goal here, not a blanket AA certification.

## Rollout/recovery

Keep PR22 Draft and retain source fingerprints, actual checkout SHA and precise
pass/fail/blocked counts. Do not approve a release from mockup screenshots or historical
candidate CI. After 01 lands, bind/run the strict suite, rerun real identity/API/worker
and actual develop regression. Use existing locked production startup and paired cold
backup/restore in AUTH_DEPLOYMENT.md/RECOVERY.md; do not change AI providers or bypass
auth to make UI tests pass. Real Google staging and live-provider quality remain separate.
