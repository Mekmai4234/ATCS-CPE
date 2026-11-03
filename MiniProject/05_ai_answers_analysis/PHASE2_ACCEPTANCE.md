# Phase 2: answer acceptance procedure

Status: procedure only. Live feature/quality acceptance remains pending until its
results are recorded against the chosen release candidate.

## Offline owner regressions

Run from `MiniProject` using the declared team dependencies and lockfile:

```sh
uv run --project 05_ai_answers_analysis --extra team --locked pytest 05_ai_answers_analysis/tests -q -W error -o asyncio_default_fixture_loop_scope=function
```

The owner HTTP tests are in `tests/test_quota_local_answer.py` within this module.
G1 (topic/source isolation) selects:

- `test_new_topic_does_not_inherit_old_keywords`
- `test_new_clip_cannot_inherit_a_previous_conversations_topic`

```sh
uv run --project 05_ai_answers_analysis --extra team --locked pytest 05_ai_answers_analysis/tests/test_quota_local_answer.py -q -W error -o asyncio_default_fixture_loop_scope=function -k "new_topic or new_clip"
```

G2 (requested-clock boundaries) selects:

- `test_out_of_range_fallback_never_returns_early_clip_citations`
- `test_fallback_time_scope_filters_neighbors_and_exposes_crossing_chunks`

```sh
uv run --project 05_ai_answers_analysis --extra team --locked pytest 05_ai_answers_analysis/tests/test_quota_local_answer.py -q -W error -o asyncio_default_fixture_loop_scope=function -k "out_of_range or time_scope"
```

Append `--junitxml=OUTPUT.xml` with an ignored evidence path to retain JUnit.
Record exact checkout/lockfile fingerprints, test selection/counts, skips and
artifact SHA-256 outside Git. These are correct-behavior regressions through
actual FastAPI, worker, SQLite and Chroma, with synthetic transcripts/vectors and
provider failure. They are not live model or semantic acceptance. The full suite
also checks authorized follow-ups, absent/visual evidence, permission failures,
provider recovery and saved/LRU reuse. G7 additionally requires the API owner's
cache/ownership evidence and the web owner's feedback evidence.

Each PR has its own head. Rerun or independently verify the evidence on one clean
integrated release candidate before certifying the matching-source main gate.
Do not substitute the historical probes that asserted the incorrect behavior.

## Live preparation and quota

Use the authorized canonical stack and existing policy/ledger. Follow
[the release runbook](../07_testing_deployment/RELEASE_RUNBOOK.md), especially its
live-check and evidence sections. Determine per-pool headroom from the current
valid policy and `gemini_reservations` for the current Pacific-day window, with
reservation/uncertain usage handled by the shared broker. Record the observation
and the operator-approved call/token caps outside Git before dispatch.

Do not establish availability from planning estimates, fixed daily-call figures
or a previous run. Never reset/copy the ledger, rotate keys/projects, enable
billing or add pools from this module to make acceptance pass. All requests must
stay within both actual broker admission and the approved shared probe budget.

## Real features and quality

1. Verify clean source/image identity, policy validity and real source readiness.
   Use the approved source inventory and successful real embeddings/readback;
   fixture IDs/vectors must not enter live cases. Use the review set maintained
   by the release owner and record the selected cases outside Git.
2. Select AI response mode (`response_mode: "ai"`) for generation acceptance.
   Retain actual questions, answers, source/version, original citation intervals,
   provider/model provenance, usage and queue/HTTP timings. Distinguish generated,
   reused, document-only, insufficient/partial and provider-failure local results.
3. Exercise chat, summary and compare here, coordinating research/quiz/study-plan
   coverage with the learning owner. Compare needs at least two ready sources.
   Use the existing worker/error policy; no independent retry loop or hidden
   model switch. Preserve failed/partial runs and stop on the agreed cap or
   policy/provider failure.
4. Use the existing release `worker_probe.py` only with its operator prerequisites:
   actually stop the normal worker before `--workers-stopped`, use the canonical
   env/authorized owner, explicit real-source cases and a fresh run key, then
   restart the normal worker. Case admissions share the enforced probe budget.
5. Human reviewers supply/approve expected answers, gold intervals, reviewer/date
   and `human_reviewed` only after examining the real results. Do not generate
   human approval or semantic scores from fixtures. Fingerprint approved records;
   changes require reapproval.

Record retrieval/provider/validation/total timings separately where available.
Keep enough samples per declared group for the release owner's latency analysis;
test-suite duration is not user-facing capacity. Machine access, test windows,
source approvals, results and quota observations belong in external evidence,
not this reusable procedure.

Live features, human quality, real import/embeddings, capacity, paired recovery,
runbook and exact integrated CI remain the corresponding owners' release gates.
This documentation does not approve main, deployment or public access.
