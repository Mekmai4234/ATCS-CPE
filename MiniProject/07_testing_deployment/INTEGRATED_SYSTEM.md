# Integrated RAG Buddy system — 24 October 2026

The maintainer authorized direct integration into `develop`, without creating another
PR. Existing module history is preserved by merge commits. `main`, the repository
default, and the MiniProject README are unchanged by this integration.

## Integrated modules

- 01: mint member UI, Google identity session adapter, admin overview/members, shared
  chat history/scope, layered Buddy with bounded pointer tracking and draggable launcher.
- 02: session/CSRF/ownership, ingestion/jobs, shared chat/history contract, readable
  credentialed session errors and an isolated test lease that tolerates CI load.
- 03: existing member-aware caption/metadata ingestion and bounded subprocess cleanup.
- 04: existing authorized retrieval, source lifecycle and SQLite/Chroma pair safeguards.
- 05: existing Gemini/RAG answer/analysis integration, citations and member history.
- 06: existing scoped research, learning plans, quizzes and flashcards.
- 07: actual-checkout regression CI, strict floating-widget tests, real-HTTP identity
  harness, locked production images and isolated local HTTPS/container verification.

## Reference-driven UI changes

The login, home and floating chat follow the supplied mint/coral concepts using real
React controls. The header uses Buddy's face, outline icons and the signed-in account.
Login combines signup/signin through the actual Google Identity Services component;
first-time account creation remains a server operation with the default `user` role.
The left scene and homepage use independent decorative learning objects, an interactive
layered mascot and a pedestal; neither screen is a baked screenshot.

Home retains the import API, the real library, scope selection and learning actions.
Video cards use actual permitted thumbnail URLs where supplied, with a visible fallback.
No example channel/view statistics or fabricated progress was introduced. Demo banners
and sample content stay explicitly identified.

The floating panel aligns above its launcher and flips/clamps at viewport edges. Drag
and click remain distinct, a keyboard/button position menu is available, and mobile
uses a focus-managed dialog. Scope/history/citations use the same state as full chat.
Overflow from decorative transformed leaves was fixed at their scene boundary rather
than weakening the viewport assertions.

## Verification and evidence

Run from `MiniProject`:

```powershell
uv sync --project 07_testing_deployment --locked
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py --group auth
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/browser_identity.py --checkout
```

From `01_web_app`:

```powershell
pnpm install --frozen-lockfile
pnpm format:check
pnpm test
pnpm build
pnpm test:production
pnpm exec playwright test
pnpm exec playwright test --config ../07_testing_deployment/playwright.floating.config.ts
node ../07_testing_deployment/scripts/ui_qa.mjs --require-floating
```

The normal browser run deliberately skips opt-in external integration cases. The
separate `browser_identity.py --checkout` executes the real frontend HTTP adapter,
API and worker, with external Google/provider fixtures; it is not real Google proof.
The dedicated 07 browser case additionally runs HTTP research and verifies logout.
UI capture reports `surface_ready` separately from production `accepted`; a passing
surface gate does not grant public release acceptance.

Python reports/JUnit are under `runtime/<run>/`, real-HTTP evidence under
`runtime/browser-identity-*/`, floating results under `runtime/floating-*`, and
responsive screenshots/traces under `runtime/ui-qa/`. Reports from before this change
are historical and may describe missing features that are now integrated.

A first concurrent baseline run exposed a one-second lease in the general 02 test
fixture. Its default is now 30 seconds; explicit expiry/heartbeat tests still use their
own clock/short lease. The corrected 02 suite is rerun, and its JUnit supersedes that
initial failure. No production timeout or ownership safeguard was relaxed.

## Running the application

### Local verification result for this integration

| Check | Result |
| --- | --- |
| Python modules 02–06, integration/full, 07 acceptance/regressions/auth | 638 cases passed across the final suite results |
| Module 01 unit | 85 passed |
| Module 01 browser | 64 passed; 8 opt-in integration cases skipped in this run |
| Dedicated module 07 floating contract | 4 passed |
| Actual HttpSessionPort/API/worker browser run | 8 passed separately, including the 7 opt-in identity cases |
| Frontend formatting/typecheck/build/production adapter smoke | Passed |
| Python Ruff lint/format | Passed |
| Responsive capture | 375/768/1024/1440px, no horizontal overflow |
| Web/API production image builds | Passed |
| Isolated production-factory HTTPS/cookie/proxy drill | Passed, cleanup passed |

The old single-user opt-in browser case is not counted as executed. Python's initial
all-group report contains the lease-fixture failure described above; `final-02.xml`
records all 106 corrected cases passing. The other 532 Python cases passed in their
independent group reports. Historical failed reports are retained, not overwritten.

These counts describe local verification, not a claim that a future GitHub Actions run
or registered Google/live-provider acceptance has passed.

For local development use a full-system environment file with the real provider key,
Google public client ID, trusted origin and paired state configuration described in
`AUTH_DEPLOYMENT.md`, module 02's `AUTH.md`, and the existing env/step/process files.
Do not paste keys into the repository. Use separate local state when experimenting.

Start the initialized API and worker with the existing preflight commands in separate
terminals. In module 01 run `pnpm dev`. Its default Vite `/api` proxy keeps API requests
same-origin; configure `NEXT_PUBLIC_API_BASE_URL` for the API target. The Google client
origin must match the actual browser origin. `VITE_DEMO_MODE=true` is a labeled preview,
not an authentication bypass for the real workspace.

For production use the existing guarded `compose.auth.yaml` overlay. The production
factory and local HTTPS/Secure-cookie drill can be tested using `docker_auth.py --checkout`
against disposable state after building the API and web images. Its cleanup removes
only the uniquely named test project, not the user's application state.

## Remaining external acceptance

- Registered real Google account login/logout on the intended origin.
- Live caption/provider access and human-reviewed answer/citation quality.
- Public HTTPS, reviewed release evidence and real-device keyboard/IME checks.

The automatic tests do not create a false release attestation, deploy publicly, change
the configured model, or claim that offline provider fixtures prove live quality.

## Branch policy

Keep `main`, `develop` and `feature/01_web_app` through the seven agreed module names.
Only remove extra branches after their exact tips are reachable from pushed develop.
`origin/<name>` is the normal remote-tracking reference, not an extra GitHub branch.
The separate clean 04 worktree is preserved by renaming its integrated handoff branch
to the canonical module name instead of deleting its checkout.
