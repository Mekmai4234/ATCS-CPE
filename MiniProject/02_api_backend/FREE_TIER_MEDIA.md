# Free-only Gemini and media evidence v2 — module 02

Base: develop `1814bf3622eb62f0963da4f682ea31661728907c`. This is the backend-owned
contract, persistence and scheduler. It does not deliver 03's extraction engine,
04/05 visual retrieval/answers or 01's new visual UI. See FREE_TIER_TEST_REPORT.md
for observed tests and release dependencies.

## Token-counting accounting correction (26 October 2026)

`countTokens` calls stay in the durable reservation ledger and still require the
verified credential, model/endpoint/role grant, owner, lease and policy pin.
They use a separate project-wide local cap of 60 requests/minute and the smaller
of the member cap and 60. Global concurrency, FIFO and provider circuits remain
in force. They do not consume the model inference RPM, TPM or rolling 24-hour
RPD budget. Generation and embedding calls continue to consume their configured
inference pool; sent/uncertain inference calls are never refunded.

Earlier code pooled token-counting calls with inference. A 20-RPD pool could
therefore reject generation after 12 token-counting calls and only 8 inference
calls. Existing rows are now classified by endpoint at admission; no usage data
is deleted, reset or rewritten. No database migration or policy-limit increase
is required. Restart both API and workers so all processes use the same code.

Google's [billing FAQ](https://ai.google.dev/gemini-api/docs/billing) excludes
token-counting from inference quota, and the Google developer support
[countTokens clarification](https://discuss.ai.google.dev/t/gemini-api-counttokens/188451)
explicitly confirms this behavior for `models.countTokens`.

Provider 429/503/504 responses remain real failures even with correct local
accounting; this correction does not guarantee external service availability.

## Compatibility and stopped upgrade

Schema **0003** adds media assets/frames/evidence revisions, private analysis cache,
media status, project reservations/waiters/circuits/policy pin and job wait metadata.
It does not alter transcript-v1 columns, old messages, sessions, owners or citations.
`Source`, `Citation` and old API readers remain v1. `SourceSnapshotV2.from_transcript`
wraps an actual transcript version without inventing one; OCR/visual snapshots use
their own evidence SHA256 and contain no transcript_version.

Fresh `yk-full init` creates 0003. For existing 0001 **or 0002**, stop API/workers
on every host, finish committed deletions, and use the selected full configuration:

```powershell
uv run --project 02_api_backend/full --locked yk-full migrate --workers-stopped --backup-dir C:/backups/yk-before-media
```

Ordinary upgrade to head refuses an unbacked 0001/0002 upgrade. The backup includes
consistent SQLite, Chroma/markers when present, and referenced media files when
present. Asset paths/hashes are checked before backup; destination must be outside
Chroma/media. `backup.json` records all source locations. Restore all included stores
together while stopped; never restore SQLite alone. Policy files live outside Git
and must be backed up separately as operator configuration. The migration does not
claim legacy owners/admins or contact Google. Populated extension-table downgrade
is refused; restore the backup. Empty extension downgrade exists for verification.

Media files live beneath MEDIA_ASSET_DIR in a database-URL namespace. When restoring
to a different database URL, copy backup/media-assets to `media.asset_root(settings)`
for that URL; do not guess a folder name. Restore drills use disposable copies.

## Local media production contract for 03

An authenticated caller queues `POST /api/v2/videos/{video_id}/enrichment`, optionally
with the existing `Idempotency-Key` header. The source must belong to that caller;
removed/deleting/foreign sources are denied. Response is the existing 202 Accepted
plus Location; poll the private job. Duplicate keys conflict on changed generation/
limits. Repeated active work for the same member/source is reused. No arbitrary
upload path, prompt, role or filesystem location is accepted from HTTP.

The configured trusted adapter must implement async `enrich(video_id, context)` and
return `evidence_v2.MediaEnrichment`. Without it, admission returns 503
dependency_unavailable. This new method is not installed on the unchanged 05 factory
by this PR. 03 should translate its PreparedMedia DTO: read frame bytes through its
own guarded asset accessor, preserve actual decoded timestamps/source hash/sampling
and OCR versions, and pass bounded bytes/text to 02. Do not parse PreparedMedia as a
transcript or pass its private asset_key as a public URL.

Worker publication checks the active durable owner, membership, lease, generation,
deletion tombstone and frozen frame limits inside BEGIN IMMEDIATE. It stores only
PNG/JPEG/WebP signatures with full content hash and bounded byte count. Decode/image
quality validation belongs to the producing extraction pipeline; signature checking
here is not an image-quality certificate. Files are hash-addressed with atomic
replacement and no adapter/client-selected filesystem paths.

Each snapshot has `{contract_version:2, video_id, generation, kind, evidence_version}`.
Evidence revisions bind source SHA256, frame content hashes, actual timestamps,
sampling/OCR/prompt versions and evidence text. Samples record timestamps and
`whole_video_reviewed=false`; they never claim full video/scene coverage.
OCR alone needs no Google key or attestation. Local work declares the trusted
adapter's `provider_operations.enrich="local"`. No browser may set this declaration.

If Gemini creates visual observations, MediaEnrichment additionally carries
requested_model, returned_model, vision_input_hash and vision_reservation_id.
Publication requires a completed approved generateContent reservation from **this
job and lease** matching model/input identity. OCR cannot be relabelled as vision
to bypass that requirement. `VisualCitationV2` binds kind/snapshot, frame, asset,
timestamp, text and exact `/api/media/assets/{asset_id}` URL. `MediaStore.verify_citation`
verifies stored evidence and the live execution scope before downstream publication.
The current execution contract is an enrichment job for one exact source/generation;
04/05 must design explicit frozen v2 multi-source jobs before using it for general AI.

## Authorized readers and independent status

- `GET /api/v2/videos/{id}/evidence` returns media state, snapshots, sampled coverage
  and OCR/visual evidence to current library members. It does not expose a server path.
- `GET /api/media/assets/{asset_id}` verifies live session, membership, generation,
  source lifecycle and file hash every request. Unknown/foreign assets use the same
  404 classification. Responses are no-store and nosniff. There is no public image
  directory, guessed-ID bypass or admin content bypass.
  Frontends should fetch private bytes with credentials, revoke temporary object
  URLs on account/session changes and never store them in a public asset cache.
- Media status is separate from transcript import. An enrichment failure/pause never
  changes a transcript-ready video's ready state. A no-caption import with explicitly
  pending media reports visual_pending; successful image-only production reports
  visual_ready with **no transcript rows or fake transcript version**.
- Existing `/api/chat` still requires transcript-ready v1 sources. Visual-ready does
  not pretend that 04/05 already support visual answers. Use the explicit v2 snapshot
  handoff and retain v1 for old jobs; do not silently widen scope or fabricate speech.
- Private analysis cache binds durable owner, video/generation, evidence version,
  prompt/model and canonical input hash. Reads reauthorize, TTL is at most one day,
  entries are bounded and a different member never receives another's analysis.
  Shared source observations must be source-only, not private user prompts/answers.

Detach removes only membership; another subscriber retains its images/evidence.
Last-member deletion uses the durable existing GC lease, waits for active readers,
then deletes generation-bounded media/cache/revision/frame data and managed files,
including hash-named temporary/orphan files. The tombstone rejects new work during
cleanup. The 03/04 delete adapter remains responsible for its extraction staging
and vector/index files before 02 completes GC. Caller-visible history stays private.

## Operator attestation, never automatic billing changes

There is no FREE_ONLY bypass switch. GEMINI_FREE_POLICY_FILE defaults to absent,
which denies outbound Gemini. The operator must inspect the actual project/key tier
and model access in AI Studio, record non-secret evidence/time and read actual quota
headings. A screenshot without headings is not a quota configuration. This software
does not inspect/change billing, change API keys, select a paid fallback or silently
change LLM_MODEL. An administrator attestation can be wrong/stale; it is a gate and
audit requirement, not proof from Google that no charge can occur.

The server-only JSON is validated by `quota.FreePolicy` (extra fields rejected):

```text
{
  "tier": "free",
  "project_ref": "NON_SECRET_CHECKED_PROJECT_REFERENCE",
  "key_sha256": "SHA256_OF_THE_CHECKED_KEY_WITHOUT_PRINTING_THE_KEY",
  "verified_by": "OPERATOR_REFERENCE", "evidence_ref": "PRIVATE_REVIEW_REFERENCE",
  "verified_at": "AWARE_ISO_TIMESTAMP", "expires_at": "AWARE_ISO_TIMESTAMP",
  "pools": {"SHARED_PROVIDER_QUOTA_POOL": {
    "rpm": RPM_FROM_AI_STUDIO, "tpm": INPUT_TPM_FROM_AI_STUDIO,
    "rpd": RPD_FROM_AI_STUDIO, "user_rpm": LOCAL_MEMBER_CAP
  }},
  "models": [{"model": "EXACT_CONFIGURED_MODEL", "bucket": "SHARED_PROVIDER_QUOTA_POOL",
    "endpoints": ["generateContent", "countTokens"],
    "roles": ["chat"], "image_capable": false,
    "returned_models": ["EXPLICITLY_APPROVED_RETURNED_MODEL"]}]
}
```

This is deliberately a template, not a ready-to-enable policy or quota claim.
Verification lasts at most seven days. Expired/future timestamps, missing/wrong key
fingerprint, paid tier, unknown model/endpoint or conflicting worker policy fail
closed. All workers must share one database and policy/concurrency settings. Models
sharing a provider quota must map to the same pool, including aliases. Embedding uses
an explicit embedContent grant. File uploads/batch/other endpoints are not approved
by this contract; do not call them outside the broker.
Model roles (chat, vision, embedding, agent) are explicitly approved independently;
vision additionally requires checked image_capable=true. A text-only approval never
enables vision implicitly. Request role defaults derive from the durable job and
endpoint, and are rechecked at dispatch; embedding count calls pass role=embedding.

```powershell
uv run --project 02_api_backend/full --locked yk-full quota-policy --workers-stopped
```

This installs the policy fingerprint without clearing usage. FullSettings exports
the same policy path and local bounds to child processes. Renew a policy while
stopped and reinstall it; inconsistent workers are refused. Returned-model drift
blocks the pool. After reviewing the actual returned model/tier and updating policy,
`quota-policy --workers-stopped --review-model-changes` explicitly clears only that
model-review circuit, not quota accounting or ordinary provider cooldowns.

For Docker mount the policy read-only at a container path and set the same
GEMINI_FREE_POLICY_FILE for API/worker/operator services via an override. It is not
copied into images. MEDIA_ASSET_DIR's default /app/runtime location is covered by
the full runtime volume. Persistent SQLite must be shared across project workers;
separate SQLite files cannot coordinate the same Google project. Other applications
using the same project are invisible to these local counters.

## Per-request adapter contract for 04/05/06 (and 03 vision)

Trusted composition declares each external operation as `gemini-broker-v1`, or
`local` only when it performs no Gemini requests. Undeclared legacy provider methods
fail closed. The declaration is a compatibility gate, not an authorization proof
of a third-party adapter's implementation. Owners must test that every actual SDK
HTTP request is wrapped, with SDK automatic retries disabled.

```python
from youtube_backend.quota import ProviderReply


async def one_http_request():
    # Exactly one SDK HTTP request, no internal retries or paid fallback.
    response = await provider_call()
    return ProviderReply(response, measured_input_tokens, observed_returned_model)


reply = await context.gemini_call(
    one_http_request,
    model=exact_requested_model,
    endpoint="generateContent",
    input_tokens=conservative_input_upper_bound,
    call_key="step-1-generation",
    input_hash=canonical_input_sha256,
)
result = reply.value
vision_proof_id = reply.reservation_id
```

Wrap countTokens, each embedding batch, generation and each agent/vision call
separately. Input estimates must include system/tools/images as applicable and be
positive. Count/embedding endpoints may report no returned model (record None);
generation must report an explicitly approved returned model. A call key is hashed
before storage; reusing it for the same job/lease never grants a second dispatch.
The input hash is required for visual publication/cache identity, not raw prompts.

The broker serializes reservations with SQLite BEGIN IMMEDIATE. It enforces shared
rolling 60-second RPM/input TPM and a conservative rolling-24-hour RPD window,
global/member concurrency, per-member RPM and interactive-before-background FIFO.
These windows are **our admission policy**, not Google's balance/reset clock. It
does not identify daily versus minute provider exhaustion from a bare 429. Background
work can wait behind sustained interactive demand; there is no completion guarantee.

Held-but-unsent calls can be cancelled/refunded. Dispatched failures, timeout or lost
workers retain conservative estimated charges; successful replies reconcile input
usage, including usage exceeding the estimate. Remote requests cannot be undone.
Dead workers' reservations lose local slots after their bounded expiry; their job
lease prevents stale dispatch/publication. No messages, images or raw errors are
stored in the budget ledger. Default local global/member concurrency are both one.

## Shared errors and durable waiting

Use `provider_errors.provider_error(status, retry_after=..., retry_delay_seconds=...)`
with only classified status and extracted retry metadata. Never pass provider body,
headers, key, prompt or full exception for persistence. Retry-After accepts finite
bounded seconds/HTTP dates; invalid/oversized values are ignored.

| Code | Meaning |
|---|---|
| provider_rate_limited / 429 | Provider limited usage; reset window may be unknown. |
| provider_unavailable / 503 | Provider outage/busy; not evidence of exhausted quota. |
| provider_timeout | Bounded request timeout; uncertain dispatched usage retained. |
| provider_configuration | Authentication/configuration rejection; no automatic retry. |
| provider_invalid_response | Invalid provider output; no silent successful answer. |
| quota_wait | Local admission budget/fairness/concurrency wait; not Google's balance. |
| free_tier_unverified / free_model_unverified | Operator attestation/model access required. |
| gemini_broker_required | Consumer adapter must implement the per-HTTP-request broker contract. |

Retry uses bounded exponential backoff+jitter within attempts/original deadline.
Provider-known waits are never shortened. Circuits retain 429/503 classification,
cannot be shortened by a subsequent failure or cleared by a concurrent old success.
`JobResponse.wait` distinguishes `retry_at` with time_source=provider from
`estimated_retry_at` with time_source=estimate. Neither is advertised as a Google
quota-reset time. An automatic attempt can additionally report scheduled_retry_at
for the application's backoff; it never overwrites the provider's earlier known
minimum with an invented provider time. A completed/running resumed attempt clears
obsolete wait metadata.

An enrichment quota/policy wait becomes **paused**, drops its lease and is not
automatically claimed all day. `POST /api/jobs/{id}/retry` is explicit member consent
to a new bounded enrichment job, including after the old deadline. Repeated retry
clicks reuse its ID; foreign/revoked owners and changed generations cannot resume it.
Known provider Retry-After schedules the new job for that time. Local estimates can
be retried explicitly but must pass the broker again. Cancel also terminates a paused
job. No background job silently extends its old deadline or impersonates a member.

## Required consumer/release work

03 must implement the real enrich adapter, staging cleanup and PreparedMedia mapping.
04 must implement permission-fenced v2 retrieval/indexing and any local OCR search;
05/06 must wrap every real provider call and adopt explicit v2 scopes/citations.
The currently merged 05 full factory has neither enrich nor broker declarations:
its Gemini methods intentionally return policy/broker errors until those changes
land. It also still constructs Gemini clients requiring a key; keyless local-only
full composition needs 05's lazy/local factory. A separately configured local
adapter can run through 02 without a Google key or attestation. Tests prove that
boundary; they do not claim the old full factory is a finished visual-only product.

Parallel proposals inspected before publishing: 03 PR #25 at
`dfda16d3b1bd1d2aae7e9c84780095f5fd201916`, and 05 PR #26 at
`387dfeddb7f5f7db91f455c12ec4b5db67ed855b`. They were not merged or tested as a
combined candidate here. In particular, #26 proposes repository.quota_broker with
grant/lease and catalog APIs; that is not a drop-in alias for this execution-bound
gemini_call contract. No misleading alias is installed. 05 must implement a trusted
bridge or align its proposal, including the currently unsupported catalog endpoint,
then 07 must run combined call-coverage tests before enabling external requests.

01 must render visual/pause states and evidence access through authorized routes.
07 must verify actual tier/model access, consumer call coverage, actual-checkout CI,
migration/restore, disk/CPU use and real media/Google acceptance. No billing or API
calls are made by this PR to certify an account or model as free.

Official references checked 2026-10-24:
[project/model rate limits and active AI Studio quotas](https://ai.google.dev/gemini-api/docs/rate-limits),
[Free Tier availability/pricing](https://ai.google.dev/gemini-api/docs/pricing),
[video inputs and sampling behavior](https://ai.google.dev/gemini-api/docs/video-understanding).
Their public documentation does not attest the user's particular project or key.
