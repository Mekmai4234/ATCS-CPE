# Free-only/media backend verification — 2026-10-24 (Asia/Bangkok)

Base: `develop@1814bf3622eb62f0963da4f682ea31661728907c`.
Branch: `codex/02-free-tier-media-contract`. All tracked changes are inside 02.
Tested implementation: `5515bcf` (the following report commit changes documentation only).
Existing user dotenv, databases, indexes and credentials were untouched. Test
attestations, model replies, PNG/OCR observations and Google subjects are synthetic;
no actual project billing status, paid provider or Google login was exercised.

## Observed results

| Check | Result |
|---|---|
| Windows backend + integration + full, warnings as errors | **180 passed**, 136.15s |
| Rebuilt full Linux Docker, networking disabled | **180 passed**, 152.23s |
| Quota/media + existing worker focused regressions | **45 passed**, 17.26s |
| Ruff lint/format and whitespace | Passed |
| All nine consumer/backend uv locks checked offline | Passed; no dependency/lockfile changes |

Both final broad runs include role-specific model/image grants, lease/deadline
revalidation after publication I/O, scoped operator circuit clearing, and separate
provider-known versus application-scheduled retry times. The full runtime smoke is
not presented as an end-to-end real visual/provider release.

## What is established

- Independent Python worker processes race against real SQLite: only one obtains
  the global reservation slot. Shared model-pool RPM/input TPM/RPD, member caps,
  concurrency, interactive/FIFO admission, duplicate dispatch and policy mismatch
  checks use durable records, not process-local counters.
- Held unsent calls can be refunded. Dispatched unknown failures retain estimates;
  success reconciles input usage. Every dispatched call has a single-use job/lease
  binding, policy fingerprint and model/endpoint identity. Renewing the policy
  does not clear accounting or let an old held grant dispatch under a new policy.
- Expired/unverified/wrong-key/paid attestations and unknown models are rejected.
  Model roles are separate: chat approval never implicitly enables vision; image
  capability must be attested. A job cannot impersonate another operation role.
  Callback tests prove no request begins before approval or after account revocation.
  Model drift blocks further calls until explicit operator review. countTokens
  can record a legitimately absent returned-model field, without inventing one.
- 503 remains provider_unavailable; 429 remains provider_rate_limited. Bounded
  Retry-After metadata is distinguished from local estimates, invalid values are
  ignored, and circuits prevent immediate repeated calls. Timeout calls are bounded
  and retain uncertain charges. No claim is made about Google's actual balance.
  Short provider hints remain distinct from the application's longer backoff; a
  provider-known retry_at is not replaced by an estimated scheduled_retry_at.
- A quota-limited enrichment becomes paused without a lease. Explicit retry after
  its old deadline creates one new consented ID and honors known provider wait;
  repeated retry clicks do not generate duplicates. The original deadline is not
  extended and transcript-ready content remains usable during media failure/pause.
- Actual HTTP/storage tests produce visual-only OCR evidence with no transcript
  rows/version. Media bytes are checked, stored privately and readable only through
  current membership/generation. Foreign/unknown asset IDs share the same 404 code;
  administrator status does not bypass content permission. Detach retains another
  subscriber's frames; last-member GC removes old-generation assets, cache, revisions
  and managed temporary/orphan files.
- Cache entries are owner/request/source/version/prompt/model scoped. Tampered
  assets, changed generations, expired publication deadlines and forged visual
  proof/citations are rejected. Visual publication requires the exact reconciled
  broker call from the current job/lease; the fixture call is explicitly synthetic.
- A populated 0002 copy upgrades additively to 0003 while retaining old sessions,
  transcript-backed results and conversation history. Unbacked upgrade is refused.
  A stopped SQLite/media backup is restored into a disposable store and the private
  image is read with the restored session. Populated-extension downgrade is refused.
  Existing full-suite actual SQLite/Chroma migration/pair-preservation tests also pass.
- The full 05 factory test rejects unverified policy, then rejects an attested but
  undeclared provider adapter before its model callback. Existing full-flow tests
  declare their replaced external transports as local in test code only. No bypass
  environment flag is added to the application.

An additional isolated custom-local composition smoke used no Gemini key or policy:
local ingestion/enrichment completed, its private PNG was readable, and health still
reported unverified Gemini. Its producer is a named local fixture, not a claim that
03's real Tesseract/media engine was tested by module 02.

## Docker and reproduction

Final broad project: `yk02-check-8f460ea129`. Report/log are in ignored
`runtime/yk02-check-8f460ea129/`. It passed locked image builds, 180 offline tests,
non-root real-factory API/worker startup, schema 0003, unverified-policy health,
SQLite/Chroma pairing, wrong-directory rejection and anonymous denial before/after
container recreation. Generated containers/network/volume were cleaned successfully;
images/reports remain locally. Unrelated Docker resources were untouched.

From MiniProject:

```powershell
uv run --project 02_api_backend --locked pytest 02_api_backend/tests/test_free_tier.py 02_api_backend/tests/test_media_v2.py -q -W error
uv run --project 02_api_backend/full --locked pytest 02_api_backend/tests 02_api_backend/integration/tests 02_api_backend/full/tests -q -W error
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_full_smoke.py
```

For focused Linux checks, run the corresponding pytest paths in the built test
image with `--network none`. No existing application data is required.

## Release limits and owner handoff

FREE_TIER_MEDIA.md specifies the exact DTOs, operator policy, provider callback and
new authenticated routes. This PR supplies module-02's storage/control plane. The
current merged 05 factory does not implement enrich or broker declarations; its
outbound Gemini methods intentionally fail closed until owners integrate every SDK
request. Its key-required eager clients also need a local/lazy composition for
keyless full-server startup. Local-only custom adapters already work through 02.

03 must supply real extraction/OCR bytes and staging cleanup. 04/05 must add v2
retrieval/answers and explicit frozen visual scope; v1 chat still rejects a purely
visual source rather than pretending it has a transcript. 06 must wrap each actual
agent request. 01 must render private frame/citation and paused states. 07 must
verify real account tier/model quotas, all consumer paths, migration/restore and
server capacity before deployment. Separate applications using the Google project
are outside the local budget ledger. A valid JSON attestation is not Google billing
verification and no numeric provider quotas have been assumed or enabled here.

No real visual answer, paid-model fallback, real Google/provider call, production
data migration, billing change or deployment is claimed. Official project/model
quota and pricing references are linked in FREE_TIER_MEDIA.md, checked on this date.
