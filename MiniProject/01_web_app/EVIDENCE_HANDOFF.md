# Visual evidence integration handoff

Scope: module 01 only, based on develop `1814bf3` and the 24 October 2026
overview/web-app documents supplied by the owner.

## Current boundary

Module 02 in this checkout has no public visual evidence, frame asset, enrichment
status, sample coverage or scheduled retry contract. Its source schema still requires
a transcript version. This change does **not** invent those HTTP endpoints, fabricate
transcripts, enable visual-only production queries or claim whole-video understanding.
The production HttpSessionPort has no EvidenceBridge. Unknown response presentation
fields are discarded. Existing transcript APIs continue to work.

The new EvidenceBridge is an internal UI adapter seam, not a proposal that module 02
has accepted. Only the test harness installs a synthetic bridge. The test-only frame
route must never be configured on production. A Draft PR is appropriate until the
contract and joint module-07 acceptance are available.

Remote refresh during this review found module 02's unmerged
`codex/02-free-tier-media-contract` at `b3bb18d` ([PR #27](https://github.com/Mekmai4234/ATCS-CPE/pull/27)). Its `FREE_TIER_MEDIA.md` publishes
`GET /api/v2/videos/{id}/evidence` and `GET /api/media/assets/{asset_id}`, independent
enrichment and `JobResponse.wait` metadata. It explicitly keeps `/api/chat` on
transcript-v1 and requires 03 extraction plus 04/05 visual retrieval/publication.
This is a concrete dependency reference, not a claim that the candidate contract
has been merged or jointly accepted. This PR neither merges nor edits that branch.
The candidate's separate provider/estimated/scheduled wait times must remain distinct
when adapting it; none means Google's daily quota reset. Do not enable v1 chat for a
visual_ready video solely because image enrichment completed.

## Contract decisions needed from 02

- Source evidence kinds and queryability, generation, evidence version and snapshot
  rules, including history and deletion/reimport invalidation without transcript data.
- Citation evidence kind, immutable frame identity, video/time association, OCR text
  and AI description; preserve per-citation availability in mixed-source results.
- Owner-authorized raster asset API, MIME/size policy, 401/403/404 semantics, no-store
  responses and protection against cross-account access. Browser checks supplement
  server authorization; they cannot establish ownership themselves.
- Enrichment stages and limitations independent of transcript readiness.
- Sample count and sampled times distinct from text coverage and entire video coverage.
- Durable queued/retrying job state and optional backend retry timestamp/Retry-After.
  Chat must resume via job GET; do not use the import/delete retry endpoint for chat.

## Implemented UI behavior

Shared full/floating evidence components show kind badges, enrichment stages,
separate escaped OCR/AI text, sample counts and timestamp links. Only a configured
adapter can enable completed visual-only sources. Transcript-ready sources remain
selectable while visual enrichment waits.

Authorized asset reads include session credentials, reject redirects/non-raster data,
limit accepted blobs to 10 MiB, and never use model-provided image URLs. Object URLs
are revoked and pending loads aborted on component cleanup/session disposal.
Image failures preserve answer text and allow an explicit image-only retry.

Known queued 429/503 jobs stop foreground observation, release the composer and stay
available for explicit GET follow-up. The backend retains responsibility for retries.
No browser timer, automatic POST repeat or invented daily quota reset is added.

## Required joint acceptance before production visual release

Implement a production bridge only after agreeing the wire contract. With module 07,
exercise a real silent video through ingestion, OCR/search, query and authorized frame
read; verify A/B access, logout/session expiry, deletion/reimport versions, missing
frames, partial coverage and queued rate limits. Fixtures do not satisfy this gate.
No Google billing, Free Tier eligibility, live Gemini or vision quality is verified here.
