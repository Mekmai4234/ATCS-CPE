# Module 01 visual evidence review — 24 October 2026

Reviewed the owner's `00_OVERVIEW (1).md` and `01_WEB_APP.md`, existing module-01
implementation, current module-02 API schemas and remote 03/05 proposals. Changes
are limited to module 01, based on develop `1814bf3`.

## Delivered

- Shared evidence badges and enrichment labels for library/full/floating chat.
- Escaped OCR text separated from AI descriptions, validated frame timestamps,
  sample-count/coverage notices and isolated image failures.
- Session-bound raster loading seam, no-store credentialed reads, no model image
  URLs, no redirect following, object-URL cleanup and abort on disposal.
- Source generation/evidence revision checks, including deletion and stale frames.
- Existing queued Gemini 429/503 jobs release foreground controls. Explicit follow-up
  reads the same job; chat never uses the import/delete retry endpoint or automatic POST.
- Backend Retry-After is shown only when supplied. No daily reset clock is inferred.
- Corrected stale README/process statements about existing auth and Buddy animation.

## Verification

- Frozen-lockfile installation: passed, no dependency changes.
- TypeScript via production build: passed.
- Vitest: **102 passed**, eight files.
- Playwright browser suite: **71 passed, 8 skipped**. Seven skipped identity cases
  run separately with the auth-enabled backend; the legacy single-user backend case
  requires its separate smoke harness.
- Production build, production authentication-boundary smoke, Prettier and diff
  whitespace checks: passed.
- Auth-enabled actual-checkout HTTP/worker suite: **7 passed**, backend `1814bf3`,
  isolated database, real API/session/worker with fixture Google verifier/providers.
  Local evidence: `runtime/identity-check-25987ff862/report.json` (ignored).

The five added browser cases use an explicitly installed **test-only** bridge:
visual-only source readiness, OCR escaping, sample coverage/timestamp/frame display
in both chats/mobile, image 403/404 survival and explicit retries, queued 429/503
GET-only continuation with unlocked UI. Unit tests additionally cover absent
contracts, unsafe MIME, 401/session disposal and generation/revision invalidation.
Production output was searched for test-only frame route/fixture markers; none found.

The first browser run exposed a regression where generic 503 text hid the deletion
failure reason; that is fixed. The touch viewport assertion now waits for the browser
resize event. A mistakenly concurrent identity invocation collided with shared ports
and trace output; it was discarded. The final browser and identity runs are sequential.

## Acceptance limits

Visual UI is scaffolded and fixture-tested; **the visual-only product acceptance is
not complete**. No production EvidenceBridge is installed. Module-02 PR #27 appeared
during the review but remains unmerged and explicitly retains transcript-v1 chat.
03/04/05 integration and joint 07 real visual/media ownership tests are still required.
See [EVIDENCE_HANDOFF.md](EVIDENCE_HANDOFF.md) for exact contract decisions and gates.

Real Google login, billing/Free Tier eligibility, live Gemini/vision quality and
deployment were not tested or changed. No live model/provider calls were made.
