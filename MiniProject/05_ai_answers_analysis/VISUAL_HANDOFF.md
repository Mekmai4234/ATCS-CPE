# 05 visual evidence and Free Tier handoff — 2026-10-24

> Integration update — 2026-10-25: text/analysis factories now use the 05 ExecutionBroker adapter bound to the real 02 SQL quota broker and durable execution lease. Every count/generate RPC is reserved and reconciled, including calls made by research tools under their actual agent role. 02 exports the shared vision/agent settings. The sections below record the original PR proposal; the proposed VisualBridge is still an internal interface, not a mounted public media-chat route. Native OCR/visual v2 storage and retrieval are in 02/04, while the public end-to-end media producer/answer route remains pending. Operator Free Tier verification is still mandatory; no billing status is fabricated.

This implements the module 05 consumer work from `00_OVERVIEW (1).md` and
`05_AI_ANSWERS_ANALYSIS.md`, against `develop@1814bf3`. Only module 05 is changed.

## Availability and upstream work

**This is an internal consumer implementation, not an enabled visual HTTP feature.**
Current 02 Source/Evidence/Citation schemas still require transcript-based snapshots;
02/04 have no visual evidence publication/image API or shared quota broker. 03's
`codex/03-local-media-ocr` provides `03-local-v1` preparation DTOs, also explicitly
internal. No sibling schema/runtime is modified and no fake transcript is produced.

| Owner | Required integration |
|---|---|
| 02 | Freeze media/evidence snapshots, owner/grants, authorized frame image endpoints; atomic final publication and quota-pending job state |
| 02/07 | Real project billing/Free Tier verification, role model allowlists and shared broker reservations across processes |
| 03 | Register prepared media with 02; keep original images/OCR and private asset keys |
| 04 | Authorized transcript/OCR/stored-observation search and final evidence/frame revalidation |
| 02 FullSettings | Export the new VISION settings through the common selected-file configuration |
| 05 | Supply the consumer, SDK enforcement, structured observation cache and mixed answer validation in this PR |

The broker and VisualBridge protocols are **05 handoff proposals** pending agreement
with those owners. Existing routes continue using existing transcript AnswerResult.
Do not mount the new dict result directly or advertise a visual capability in health.
The old backend does not know `quota_pending` as a paused state; durable pause/resume
is an upstream task, not implemented by renaming an error in 05.

## Free Tier enforcement and text compatibility

All Gemini SDK operations owned by 05, including text generation, countTokens and
catalog lookup, now require a trusted injected `QuotaBroker`. Factories look for a
server-provided `repository.quota_broker`; no such attribute exists in current 02.
Without it, generation fails `quota_pending` before network. This deliberately changes
live text availability until integration is supplied; deterministic transcript display
and offline model doubles continue to work. A key, `--live`, model name or FREE_ONLY
boolean cannot authorize billing or establish free access.

The broker must bind externally verified project/credential fingerprint, role-specific
allowlist, actual image API capability, supported output/thinking limits, exact returned
versions and verification expiry. The consumer rechecks grants around queued requests,
requires separate reservations for count and generation, passes conservative input/output
budgets and records actual generation usage even for rejected output. SDK retries are
disabled per operation, including injected SDK clients. No model/key/provider fallback,
billing change, project creation or catalog-based capability inference is implemented.
Requested LLM_MODEL is unchanged; VISION_MODEL stays blank until an administrator
selects a model verified free for the actual project. Changed aliases require verification.

The broker must atomically account for requests/tokens/concurrency across ALL project
consumers, including failures/cancellation. The protocol is not a working central quota
service; the offline broker double is not imported by application startup. 03/04/06
Gemini clients are outside this PR and must also join that broker before a full-system
Free Tier release. In particular, the legacy team factory's embeddings/Agent are not
made Free Tier safe merely because 05 text generation is gated. Do not run live full-team
acceptance until all of these paths are integrated and verified.

## Media bridge and observations

`prepared_frames(...)` maps selected `03-local-v1` frames only after bridge authorization,
checking media version, duration, frame count and timestamps. A trusted frame_locator
maps private asset keys to a relative, authenticated image API path; file paths/external
URLs/token URLs never enter citations or model requests. `MediaSnapshot` uses evidence
version plus video generation, without a fabricated transcript_version.

`VisualAnswerService.observe` obtains original bytes through the trusted bridge and
checks MIME signature, byte limit and SHA-256. It sends a single inline image and OCR
as untrusted user data, with a separate immutable system policy and structured schema.
Frame identity/time come from trusted metadata, never provider output. Observations
contain visible objects/actions/readable text and explicit limitations; original OCR
remains separate. No full video URL/file upload, OCR cloud service or tool calling is added.
Semantic OCR/image accuracy still needs evaluation against real images.

The SQLite observation key includes owner/grant scope fingerprint, project, image hash,
source generation/evidence version, original OCR, requested model, one pinned returned
version, prompt policy/version and schema. Every hit rechecks current authorization and
frame validity. Removed/replaced grants, changed snapshots and changed model versions
cannot reuse the old key. The cache stores observations only, not private answers/history.
It is a private server file with a 10,000-entry eviction ceiling. Operational byte/retention
budgets need deployment sizing. A per-instance lock deduplicates concurrent requests in
one service; cross-process in-flight deduplication belongs in the shared broker/store.

## Mixed answers and limitations

The consumer searches authorized transcript/OCR/stored observations first. Only an
insufficient result selects additional relevant frames, at most 3 per question (12
prepared frames per clip, duration at most 600 seconds). Existing cached observations
reuse local storage without another image/provider call. JSON, citation allowlists,
source generation/version, frame identity and current permissions are checked before
return. 02 must still perform its own atomic final publication and owner-scoped polling.

Results retain evidence kind, frame/time, evidence version and authorized image locator.
Application-rendered citation labels identify transcript/OCR/sample-image and timestamps.
Coverage reports inspected frames separately and always states whole_video_reviewed=false.
Silent/unclear/missing evidence can return insufficient_evidence; provider 429/503 remain
generation_rate_limited/generation_provider_busy and are never invented answer fallbacks.

Face/appearance and unlabelled performer requests are refused before model calls for
recognized request patterns. Performer attribution requires explicit time-linked labels
from trusted evidence. Policies also prohibit face/voice/lip identity inference, fabricated
speech/lyrics and obeying OCR instructions. These lexical/prompt checks are safeguards,
not proof that arbitrary adversarial wording or a real model can never violate policy.

## Verification and official references

See [VISUAL_TEST_REPORT.md](VISUAL_TEST_REPORT.md) for executed results and limits.
No actual Free Tier account, billing, quota, image understanding or video quality was
verified using live API calls in this task. The PR remains a draft pending upstream
contract integration and review.

Official documentation consulted on 2026-10-24:

- [Pricing and model tiers](https://ai.google.dev/gemini-api/docs/pricing)
- [Billing](https://ai.google.dev/gemini-api/docs/billing)
- [Project-level rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Image input](https://ai.google.dev/gemini-api/docs/image-understanding)
- [Thinking compatibility](https://ai.google.dev/gemini-api/docs/thinking)

No fixed Google quota is assumed from these links; active access/limits require the
actual project's evidence. A successful catalog lookup alone does not establish access.
