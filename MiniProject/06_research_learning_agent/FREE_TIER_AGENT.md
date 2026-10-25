# Free Tier admission and opt-in media Agent

2026-10-25. Module 06 consumer changes on develop 1814bf3. No billing, credential,
model selection, public route or other module is changed.

## Shared admission

Every real 06 countTokens and generateContent request requires the leased context's
gemini_call from 02 PR #27. The SDK configuration credential must match the backend
credential. The backend validates operator-attested Free Tier/model grants, roles,
project-wide limits and returned versions before accepting output. Missing context or
verification fails before even countTokens. 429/503 are normalized inside the callback,
so 02 settles the correct error. No retry, key rotation, paid/model/provider fallback
or automatic tier change is introduced. Requested/returned models remain recorded.

Defaults per run: four model operations, 32 tool calls, at most three additional frames,
and existing bounded steps/time. These are application ceilings, not Google quotas.
Model operations count attempted planning, learning generation and delegated image
observations. countTokens is an additional outbound request, separately charged by 02.
Conservative operation accounting may include a delegated 05 cache lookup with no API call.

Research preserves the last logical model operation for finish_research, two tool calls
for final source validation, and finalization time. Media learning leaves room for a
finish decision plus artifact generation. Insufficient quota before evidence propagates
to 02; after evidence, research can return a checked local partial without another model
call. Auth/source/cancellation errors remain terminal. Progress contains operation
summaries and counters, never private model reasoning.

This is a local run allowance plus per-dispatch project admission. 02 does not yet expose
an atomic reservation for several future planning/final calls. Other users can consume
project quota before final dispatch; the supported fallback is a validated local partial,
not a guarantee that a final Gemini request will have capacity. A joint 02/06 reservation
handoff must avoid holding a concurrency slot while waiting for another slot.

AgentSettings accepts agent_max_model_calls, agent_max_tool_calls and agent_max_extra_frames.
Resolved backend fields are used when available, otherwise 06 defaults apply without
reloading module env files. Trusted composition can explicitly inject AgentSettings.
The existing LLM_MODEL default is not silently replaced.

## Media boundary

AgentAdapters.research_media is opt-in and returns internal schema_version=06-media-v1.
It accepts native 02 SourceSnapshotV2 and exports exact VisualCitationV2 frame/time/asset
routes. It never fabricates transcripts, modifies v1 ResearchResult or publishes through
the v1 job/result schema. No REST endpoint or backend job kind is introduced.

RagMediaTools uses 04 PR #29's current scope/inventory/lexical search/evidence interfaces.
Stored OCR/visual descriptions are read first, without embedding requests. Final output
and cache hits are checked against current ownership and storage. Foreign frames, revoked
grants, changed versions and invented citations fail closed. Whole-video coverage stays
false. Having OCR on a frame does not mean a visual description is already cached.

inspect_frame delegates an authorized frame_id to a server-provided 05 bridge. 06 creates
no image client and reads no arbitrary URL or filesystem path. The bridge must use 05's
authorized observation cache and the same 02 broker, returning registered native evidence
for that frame and frozen versions. Repeated frame actions cannot generate repeatedly.
Quiz/flashcards/study-plan items cite the same checked IDs, kinds and versions.

**Current integration limit:** 04 admits native media reads under enrichment leases only;
02 intentionally does not permit the agent planning role on an enrichment lease. 05
PR #26 has an opt-in visual proposal with a different DTO. This PR performs no implicit
conversion, role downgrade or invented registration. Local OCR-only internal output works
now. Public multi-step media research and new observations still need joint 02/04/05
scope, publication and bridge wiring. Planner/vision default to disabled on the media
entrypoint; supplying a Gemini planner on a disallowed lease is rejected by 02.

## Verification and operator responsibility

FREE_TIER_REPORT.md records exact candidate inputs and test results. Contracts exercise
real 02 durable admission with mocked SDK HTTP: separate count/generation reservations,
missing verification, credential mismatch, 429/503 and no retries. Core tests include
actual 02/04 image-only lexical retrieval plus bounded synthetic planner/05 callbacks.
They do not establish live OCR/visual quality or a completed public media workflow.

Operators must verify project/model eligibility in AI Studio; a flag cannot change a paid
project. Limits apply to the project, not each key. Primary references checked:
[rate limits](https://ai.google.dev/gemini-api/docs/rate-limits),
[pricing](https://ai.google.dev/gemini-api/docs/pricing),
[billing](https://ai.google.dev/gemini-api/docs/billing).
No account billing, live quota or paid provider was inspected or changed here.
