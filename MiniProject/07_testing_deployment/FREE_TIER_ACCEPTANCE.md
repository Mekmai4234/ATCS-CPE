# Free Tier / visual media acceptance — 25 October 2026

**Release blocked.** This is module 07's verification and deployment preparation,
not implementation of modules 01–06's pending visual/Free Tier features. Base develop
is `1814bf3`; the source used for default CI is always its actual merge-test checkout.
PRs 25–30 are separate proposals. Do not replace default CI with their pinned archives.
See [FREE_TIER_REPORT.md](FREE_TIER_REPORT.md) for measured results and exact candidate pins.

## Offline commands

From MiniProject:

```powershell
uv lock --check --project 07_testing_deployment
uv sync --locked --project 07_testing_deployment
uv run --no-project python 07_testing_deployment/scripts/source.py record --record 07_testing_deployment/runtime/checkout-source.json
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/check.py
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/check.py --group auth
uv run --no-project python 07_testing_deployment/scripts/source.py verify --record 07_testing_deployment/runtime/checkout-source.json
# Strict FEATURE gate: expected nonzero while v2/broker features are absent/incompatible.
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/check.py --group free-tier
# No credentials or network needed. Unknown/unreviewed tier exits 2, not success.
uv run --locked --project 07_testing_deployment python 07_testing_deployment/scripts/free_tier.py
```

`check.py` clears Gemini/OpenAI/auth/media/quota/live opt-ins. Baseline regression
excludes the explicitly marked `free_tier_contract` tests; those tests are a separate
strict gate and **fail**, never skip to green, when features are missing. Default CI
includes local tool QA; the separate manual `miniproject-free-tier.yml` runs the strict
feature contract on its actual checkout. Passing either is not full release acceptance.

## Required evidence matrix

| Gate | Required checks | Current evidence / remaining work |
| --- | --- | --- |
| v2 + v1 | OCR/visual snapshots without fake transcript; authorized frame/time citation; unchanged v1 serialized Source/history | Strict 07 schema checks; v2 absent from develop. Candidate passes schema checks; old history/owner comparison must also pass actual backend migrations and combined consumers |
| Migration/recovery | Disposable SQLite + Chroma + referenced media; v1 readers; upgrade/restore; no real data fixture | 07 cold backup v2 includes `media/`, accepts v1 backup format, verifies image checksums; actual SQLite/Chroma restore regression. 02 candidate migration/media cases pass separately; full combined migration remains blocked |
| Privacy | Revoke/delete during OCR, vision, finalization; stale generation/job lease; private image authorization | Candidate 02 tests exercise publication/access fences; local tools do not certify application permissions. Repeat via real combined worker before release |
| Seven clips | Silent sign/no text, mixed speech/image, brief event, injection text, unnamed person, unclear Thai/English | Seven original tool fixtures generated; real OCR/frames retained. Mixed clip has a synthetic tone and sidecar caption, avatar is geometry: **real speech/face-scene and model semantics remain pending** |
| Provider errors | 429/503/Retry-After/unknown reset/timeout/permanent config; attempt/deadline preserved | Actual develop retry regressions retained; candidate 02 quota tests cover provider normalization/accounting. Combined embedding/vision/agent transports still need verification |
| Shared budget | Independent worker races; chat/embedding/vision/agent and countTokens through same execution-bound broker; no hidden SDK retry | Candidate 02 races pass. 05 authorize/async-reserve interface differs from 02; strict consumer test fails. This is a release blocker, not a missing compatibility alias in 07 |
| Cache/fallback | Cache hit reduces observed HTTP calls; exhausted quota parks without busy loop; no paid fallback/key rotation | Consumer unit fixtures are insufficient for whole-project call coverage. Instrument actual combined HTTP boundary; never infer quota units from HTTP batch count |
| Browser | Thai wait/error text, media citations, phone/keyboard/focus, resumed/completed job unlocks once | Existing actual UI/browser regression retained. Free Tier UI PR28 scaffold is not end-to-end real media/browser acceptance |
| Tier/model | Operator AI Studio/project/key match, dated actual limits and role-specific model access/aliases | Unknown here; no key/account/billing operation performed. Catalog result is not acceptance. Keep Gemini outbound disabled |
| Capacity/health | Queue/wait/error rate, cache-hit denominator, actual request/token counters, wall/CPU/RAM/disk/cleanup; agreed server workload | Local tiny-clip CPU/wall/RSS/disk measured under limits. Actual server capacity, real cache/provider metrics and concurrent heavy clips remain pending |
| Deployment | Same reviewed source/images, locked dependencies, non-root API/worker, shared local SQLite/quota state, resource/retention controls | Existing split containers retained. Local tools packaged separately; production worker integration and image/source attestation remain blocked until upstream contracts align |

## Free Tier release gate

`free_tier.py` is an **offline checker of operator evidence**, not an AI Studio client
and not a switch that turns a Paid project into Free. `preflight.py --run api|worker`
now requires this gate before pair access or process launch; inspection/initialization
without `--run` still supports offline maintenance. An explicit evidence file is also
checked before `--initialize` when selected. Do not use the old production startup
instructions to bypass the Free Tier requirement.

Evidence must be a private JSON file, supplied as `--free-tier-evidence PATH` or
`FREE_TIER_EVIDENCE_FILE`. It must contain:

- `schema: 1`, `tier: "free"`, `project_ref`, `reviewed_by`, `evidence_ref`, and actual
  boolean `ai_studio_checked`, `key_project_match`, `model_access_checked` all true.
- Aware `checked_at`/`expires_at`, with a validity window no longer than 24 hours;
  `key_sha256` matching the selected server key. Do not put the API key in the artifact.
- Exact clean `revision` and `source_sha256` from `source.py`. A dirty or pinned candidate
  cannot certify the deployment. The current Gitless runtime image cannot satisfy this
  checkout proof; **image attestation integration is still a release blocker**, not
  permission to trust caller-controlled environment labels or skip provenance.
- `models` keyed separately by `chat`, `vision`, `embedding`, `agent`. Each grant contains
  `requested_model`, nonempty `returned_models`, `endpoint` (`generateContent` or
  `embedContent`) and positive integer `rpm`, `tpm`, `rpd`, matching the actual reviewed
  project/model limits and the configured backend FreePolicy. Do not silently edit
  LLM_MODEL/embedding settings or treat catalog access as a working grant.
- `smoke_budget` with explicit `max_requests` (1–3) and `max_input_tokens` (1–4096).
  These are conservative **local trial ceilings**, not Google quotas.
- `checks`, with all named gates in `scripts/free_tier.py:CHECKS` reviewed true for that
  exact source. They are assertions requiring retained test artifacts, not test results
  generated by the checker itself. The matching backend policy remains independently
  required; production consumers must enforce each real request/reservation.

The legacy `live_smoke.py` is deliberately blocked **even with accepted evidence**:
its API can fan out into multiple model calls and does not expose an enforceable
per-smoke request/token budget. Re-enable a small live smoke only after that end-to-end
broker route is implemented and checked. No new paid/OpenAI/Cloud Vision fallback is added.

The isolated container auth/startup drills use `offline_start.py`, their exact synthetic
key and internal-only Docker network. They do not submit generation/import jobs or
create a release artifact; real keys are rejected by that test-only launcher.

## Rollout and recovery

1. Align the 02 execution-bound broker with all real 03/04/05/06 provider entry points;
   refresh locks in the appropriate module branches, then rerun actual integrated develop.
2. Keep media references, upload staging and finalization scoped by owner/generation.
   Agree retention and a global disk quota before accepting public uploads.
3. Configure shared SQLite/Chroma/**media** on the same backed-up state tree and local
   filesystem, not separate per-worker quota databases or an unverified network share.
   Stop all writers/clients, finish/cancel pending jobs, then use RECOVERY.md. Version 2
   backups include `state/media/`; an external media path is **not** implicitly backed up.
4. Restore into a new tree, verify hashes/inventory/citations, run disposable migration
   and privacy drills, and retain the old pair. Never use real stores as test fixtures.
5. Set and measure worker-wide CPU/RAM/PID/disk limits on the owner's existing server;
   use serial Gemini concurrency initially. No host purchase or unlimited video claim.
6. Require operator tier/model verification, real bounded smoke, browser integration,
   registered Google login/public HTTPS and image/source attestation before release.

Official references checked on 25 October 2026: [pricing](https://ai.google.dev/gemini-api/docs/pricing),
[project-level rate limits](https://ai.google.dev/gemini-api/docs/rate-limits),
[video understanding](https://ai.google.dev/gemini-api/docs/video-understanding).
Current limits are project/model/account dependent; this task did not inspect private quota.
