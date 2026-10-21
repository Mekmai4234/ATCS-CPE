# Google identity and multi-account verification

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
| Legacy migration/explicit owner claim, paired backup, last-admin protection | Upstream 02 identity suite; 07 recovery tests | Run on disposable state only |
| Signed vector cursors and context revocation | Upstream 04/06 suites in the combined candidate | Any upstream failure blocks acceptance |
| Session switch, direct admin URL, expiry, back/cache, keyboard/mobile | Module 01 browser tests through 07 Playwright config | SessionPort/GIS fixture; not backend login E2E |
| Desktop/mobile images | Candidate `01_web_app/runtime/screenshots` at 375/768/1440 px | Visual evidence; no supplied design image exists in this task for pixel comparison |
| Google → real backend → import/chat/citation/research/artifact | **Blocked**: frontend PR 17 intentionally uses PendingSessionPort | Must pass after real adapter integration |
| Google account selection/cancel/relogin/logout/switch | **Manual pending** with registered client ID and team accounts | Never save account passwords or credentials |

The 07 verifier is injected only into a disposable app with `app_env=test` and fixture
adapters. It is not an environment flag, endpoint, or production dependency. Runtime
Docker images copy scripts, not tests. Production auth must continue using Google's
verification library. See Google's [token verification guidance](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

## Repeatable commands

From MiniProject:

```powershell
uv sync --project 07_testing_deployment --locked
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py
# Strict: exits nonzero if module 02 has no auth implementation. No skip-to-green.
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/check.py --group auth
```

The default runner preserves existing single-user regression coverage and excludes the
separate strict auth group. It clears inherited auth/provider settings. The root CI
runs auth automatically when `02_api_backend/src/youtube_backend/auth.py` exists; on
old develop it states the blocker. Baseline green does not mean multi-account ready.

Prepare a candidate without changing 01–06 or merging unreviewed PRs:

```powershell
git fetch origin
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/candidate.py --module-ref 01_web_app=origin/feature/01_ragbuddy_google_ui --module-ref 02_api_backend=origin/codex/02-google-auth-ownership --module-ref 03_video_ingestion=origin/feature/03_member_video_ingestion --module-ref 04_rag_knowledge=origin/codex/04-authorized-rag-sources --module-ref 06_research_learning_agent=origin/codex/06-member-research-learning
```

The printed directory contains immutable module SHAs in `candidate.json`. Each selected
module is archived from that exact ref; unselected modules come from the base SHA.
Current 07 tooling is copied without runtime, secrets or virtual environments. Archives
force LF independent of Windows checkout settings. The candidate lock must be regenerated
there because pending module dependency metadata differs; never copy that lock to develop.
Within that printed candidate directory:

```powershell
uv lock --project 07_testing_deployment
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
```

Run baseline and candidate browsers sequentially: upstream test servers use the same
ports. On a normal Windows CRLF checkout, Prettier can be run with `--end-of-line auto`
to distinguish formatting defects from checkout conversion; CI Linux enforces tracked LF.
To capture additional login/admin visual evidence on the new UI candidate, run
`node 07_testing_deployment/scripts/capture_ui.mjs --allow-demo` from that candidate.
It captures 375/768/1440 px views, blocks nonlocal browser requests and explicitly labels
the evidence as demo. This helper requires the new UI; it does not add Google integration.

One backend browser scenario is intentionally skipped by upstream unless its fixture API
is running. Do not count that skip as integrated identity evidence.

`tests/auth/test_domain.py` additionally runs auth-enabled 02–06 services and real Chroma,
including private chat/research/quiz access, with external providers doubled. Existing
single-user domain regression chooses auth=false explicitly in test settings; strict
domain acceptance always uses auth=true. This is still separate from a production factory
deployment and real browser-to-backend Google flow, which must pass before release.
Gemini/captions and answer-quality review remain separate paid, opt-in acceptance.
