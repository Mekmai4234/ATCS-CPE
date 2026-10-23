# Google identity and multi-account verification

24 October source policy: default PR/push CI tests the actual checkout, with before/after
`source.py` fingerprints. The candidate commands/matrix below describe historical opt-in
integration work; they are not the current default or proof for later source. See
[FLOATING_UI_ACCEPTANCE.md](FLOATING_UI_ACCEPTANCE.md) and [UI_CHECKOUT_REPORT.md](UI_CHECKOUT_REPORT.md).

Updated 22 October: use the exact manifest and committed auth consumer lock below.
The previous PendingSessionPort/29-failure result is historical; current results are in
[REVIEW_AUTH_FIX_REPORT.md](REVIEW_AUTH_FIX_REPORT.md). Real Google remains pending because
no registered staging origin/client ID is available, as confirmed by the user.

Scope: 07 tooling/tests/deployment plus the authorized root workflow. This document
implements the new 00/07 plan as a verification boundary; it does not implement the
production auth or frontend adapter owned by 01/02.

## Evidence classes

| Check | Implementation / evidence | Release meaning |
| --- | --- | --- |
| A/B/admin/suspended, first user never admin | `tests/auth/conftest.py` and `test_members.py` | Real backend routes/database; external verifier and worker providers are fixtures |
| Audience/issuer/expiry/nonce, forged credential, login/API CSRF, rotation/logout | Strict 07 auth suite; upstream 02 identity suite also checks RSA signatures | Not an actual Google account sign-in |
| Library filters/pagination, transcript, job IDs/cancel/retry, conversations, research event cursors, artifacts | Strict 07 auth negative tests | Admin also cannot read another user's private IDs |
| Shared concurrent pending imports/detach | Strict 07 auth suite plus upstream 02 execution/GC tests | No provider credit used |
| Legacy migration/explicit owner claim, paired backup and restore | `tests/auth/test_migration_drill.py` + upstream 02 identity suite | Real fixture SQLite/Chroma copy; operator CLI and pre/post-migration restore |
| Signed vector cursors and context revocation | Upstream 04/06 suites in the combined candidate | Any upstream failure blocks acceptance |
| Session switch, direct admin URL, expiry, back/cache, keyboard/mobile | Module 01 browser tests through 07 Playwright config | SessionPort/GIS fixture; not backend login E2E |
| Desktop/mobile images | Candidate `01_web_app/runtime/screenshots` at 375/768/1440 px | Visual evidence; no supplied design image exists in this task for pixel comparison |
| Real frontend adapter → backend → import/chat/citation/research/artifact/admin | `scripts/browser_identity.py`, upstream identity scenarios + 07 research browser scenario | Real HttpSessionPort/API/worker; external Google verifier/GIS/providers doubled, HTTP loopback |
| Google account selection/cancel/relogin/logout/switch | **Manual pending** with registered client ID and team accounts | Never save account passwords or credentials |

The 07 verifier is injected only into a disposable app with `app_env=test` and fixture
adapters. It is not an environment flag, endpoint, or production dependency. Runtime
Docker images copy scripts, not tests. Production auth must continue using Google's
verification library. See Google's [token verification guidance](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

## Repeatable commands

From MiniProject:

```powershell
uv run --no-project python 07_testing_deployment/scripts/candidate.py --manifest 07_testing_deployment/integration.json
# Change directory to the printed candidate root.
uv lock --check --project 07_testing_deployment
uv sync --project 07_testing_deployment --locked
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py
# Strict: exits nonzero if module 02 has no auth implementation. No skip-to-green.
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py --group auth
```

The default runner excludes the separately executed strict auth group. It clears
inherited provider/auth settings. Root CI tests both groups on actual checked-out source.
Pinned manifests are manual-only. Missing contracts/stale locks fail; no fallback replaces source.

Prepare a candidate without changing 01–06 or merging unreviewed PRs:

```powershell
git fetch origin
uv run --no-project python 07_testing_deployment/scripts/candidate.py --manifest 07_testing_deployment/integration.json
```

The printed directory contains immutable module SHAs in `candidate.json`. Each selected
module is archived from that exact ref; unselected modules come from the base SHA.
Current 07 tooling is copied without runtime, secrets or virtual environments, with
commit/dirty-state/tooling and lock fingerprints. Archives force LF independent of
Windows checkout settings. The committed 07 lock now includes the auth dependency
metadata: verification MUST NOT regenerate it. Change it only as a reviewed source fix.
Within that printed candidate directory:

```powershell
uv lock --check --project 07_testing_deployment
uv sync --project 07_testing_deployment --locked
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py --group baseline
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py --group auth
Set-Location 01_web_app
pnpm install --frozen-lockfile
pnpm typecheck
pnpm format:check
pnpm test
pnpm build
pnpm test:production # new UI PR supplies this additional bundle isolation check
pnpm exec playwright install chromium
pnpm exec playwright test --config ../07_testing_deployment/playwright.config.ts
Set-Location ..
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/browser_identity.py
```

Run baseline and candidate browsers sequentially: upstream test servers use the same
ports. On a normal Windows CRLF checkout, Prettier can be run with `--end-of-line auto`
to distinguish formatting defects from checkout conversion; CI Linux enforces tracked LF.
To capture additional login/admin visual evidence on the new UI candidate, run
`node 07_testing_deployment/scripts/capture_ui.mjs --allow-demo` from that candidate.
It captures 375/768/1440 px views, blocks nonlocal browser requests and explicitly labels
the evidence as demo. This helper requires the new UI; it does not add Google integration.

The general browser run skips upstream opt-in backend cases; the separate identity
runner enables and runs the actual adapter scenarios. Do not count general-run skips
as passes. The older standalone workspace/backend scenario remains outside identity E2E.

`tests/auth/test_domain.py` additionally runs auth-enabled 02–06 services and real Chroma,
including private chat/research/quiz access, with external providers doubled. Existing
single-user domain regression chooses auth=false explicitly in test settings; strict
domain acceptance always uses auth=true. This is still separate from a production factory
deployment and real browser-to-backend Google flow, which must pass before release.
Gemini/captions and answer-quality review remain separate paid, opt-in acceptance.
