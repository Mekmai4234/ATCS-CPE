# P0/P1 delivery and remaining acceptance — 30 October 2026

## Review follow-up

Merged `origin/develop` (`9f569ea`, already up to date) on the module branch before
editing. Addressed #35 by replacing the obsolete position-menu controls with the
supported keyboard Home reset. The test drags the launcher away, asserts movement,
resets to its actual bottom-right bounds above mobile navigation, checks containment,
and opens with Enter again while localStorage throws. Desktop and mobile cases retain
focus/open/drag/resize/composition coverage; nothing is skipped to hide the old failure.
Latest Floating Buddy browser suite: **5 passed**; scoped Prettier check passes.

Expanded the actual 02/04/06 handoff from one case to eight: default reuse, explicit
point/range reuse, out-of-window and straddling stored evidence requiring fresh in-window
observations, invalid/reversed times preventing publication, and an independently
configured vision model. Successful results preserve exact intervals through history,
cold backup/restore and revocation. The suite passes on the 07 branch's legacy native
fallback and on the coordinated corrected branches. Latest Windows handoff: **8 passed**;
latest combined Docker full 07 suite: **83 passed**, including strict Free Tier cases.

All owned-module Ruff/format checks pass. The shared base still has a confirmed Ruff
format failure in module 05's `youtube_answers/team.py`, and standalone CI needs the
owned 02/04/07 changes integrated into develop as well. That out-of-scope 05 file was
read for diagnosis but not edited. New CI runs are recorded on the updated PRs; local
and Docker results do not claim that the shared CI or P0 human/live gates are accepted.
This follow-up makes no provider requests and does not change quota policy or ledger.

User-selected scope: modules **02, 04, 06, 07**, P0/P1 only. Each branch was updated
to develop `9f569ea` before editing. PRs target develop separately; no 01/03/05,
root configuration, GitHub workflow or external TODO file was edited. P2/P3 remains
deferred. 06's shared reuse needs the 04 PR; existing installations retain native
fallback. The 07 handoff test verifies fallback on the base checkout and zero new
vision calls when the coordinated 04/06 branches are loaded.

## Delivered

02: typed private member/admin quota status, local-versus-provider wait reasons and
timestamps, idempotent explicit resume of retryable generation work with frozen
sources, and immutable revision/retention handoff. 01 owns the later UI integration.

04: local topic/time catalogue across separately typed transcript, OCR, visual and
native observations; actual adjacent transcript context; filtering before result caps;
per-source balanced results; owner/grant/lease/version/model/expiry fences. It reuses
existing immutable stores and makes no embedding/generation call. Scores are lexical
candidate relevance, not confidence. 05's answer-path integration is outside scope.

06: use relevant current private observations before inspecting video again; retain
full qualifications/canonical IDs; reject normalized duplicate questions/card fronts
without erasing Thai tone marks; keep the single-video native contract until P3.

07: 36 proposed real-video questions, human-gold gate bound to exact question/answer/
source version, latency aggregation with explicit missing stages and minimum sample
counts, capped live learning probe, local-only library benchmark, and integrated
publication/history/revocation/cold-restore tests. Git is now installed only in the
Docker test stage because existing provenance tests execute it. Runtime stays unchanged.

## Commands (MiniProject root)

```powershell
uv run --project 07_testing_deployment --locked pytest 07_testing_deployment/tests -q -W error
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/evidence_review.py 07_testing_deployment/fixtures/video_review_36.json --output 07_testing_deployment/runtime/p1-gold-gate.json
```

The gold command deliberately exits **2** while review is pending. For each case a
human must inspect the clip, enter the expected answer, actual source version,
timestamped references and dated review, then set `case_sha256` to the SHA-256 produced
by `evidence_review.fingerprint(case_without_review)`. Changing any reviewed fact
invalidates the hash. A ready gold dataset still does not certify any model's answers;
review generated claims, citation support, timing and correct abstention separately.
The two English clips are planned additions, not imports or availability claims.
Inspect caption mismatch/replay cases during review rather than assuming they exist.

An explicitly authorized real-provider run creates audited jobs/artifacts in the
EXISTING application store and ledger; do not copy its key to a fresh accounting DB:

```powershell
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/learning_probe.py --allow-live --env-file YOUR_FULL_ENV --owner YOUR_MEMBER_ID --video-id YOUR_READY_VIDEO --topic "From the visual scene at 00:00-00:05, what is directly visible?" --max-calls 8 --max-tokens 200000 --run-key YOUR_UNIQUE_REVIEW_RUN --output 07_testing_deployment/runtime/live-learning.json
```

Every endpoint/role passes the normal shared SQL broker AND the trial cap, including
05's direct reserve/dispatch/settle path, countTokens and embeddings. Failed/uncertain
calls retain trial allowance; the probe stops on the first failure and cancels queued
automatic retry work. Existing run keys are refused. A successful run must publish
and reread all three artifacts with matching content/citations/current grants. Report
semantic review as pending until a person checks it. This is not public deployment
acceptance and does not bypass or mint the separate release attestation.

The local benchmark also records an audited, cancelled research job but forbids all
provider reservations, so it cannot consume model quota:

```powershell
uv run --project 07_testing_deployment --locked python 07_testing_deployment/scripts/library_benchmark.py --allow-state-probe --env-file YOUR_FULL_ENV --owner YOUR_MEMBER_ID --video-id YOUR_READY_RAG_VIDEO --questions 07_testing_deployment/fixtures/rag_lookup_questions.json --output 07_testing_deployment/runtime/library-timing.json
```

## Measured results and boundaries

Local retrieval on existing real clip `cWVse_LuFO0`: first lookup **39.52 ms** (n=1),
same question n=20 **p50 23.66 / p95 24.21 ms**, different questions n=20
**p50 26.06 / p95 29.42 ms**. Provider calls: **0**. These measure local lookup after
factory startup, not answer-cache latency or full HTTP/worker/model latency. Queue
time is unmeasured (null); percentiles use nearest rank and remain null below 20
samples. Returned evidence still needs semantic review. This one local corpus is not
a short/long-clip service SLO. Private runtime JSON records samples, source versions
and loaded-package source hashes; no user IDs, credentials or transcript texts are
included in the committed report.

The live learning probe on real clip `C0DXctGPWxw` declared 8 calls / 200,000 input
estimate tokens. It attempted **2** admissions, debited **111,477** conservative trial
estimate tokens and stopped at **provider_unavailable** during Quiz. Dispatch-to-
settlement time was **13.08 seconds**, including SDK handling. This does not establish
successful schema acceptance or model quality. Flashcards/study plan were not run.
No policy, key, model, project limit, tier or existing ledger was reset/raised/rotated.
Raw diagnostics remain ignored under 07/runtime/p1-live-learning.json and
07/runtime/p1-library-timing.json; hashes bind the code actually used for those probes.

P0 remains **not accepted**: 36 gold answers/references await human review; the
real-provider learning route still needs a successful run when the provider is
available. Do not report schema/permission tests as answer-accuracy scores.

## Automated validation

All module images were built from their own Dockerfiles. Final tests run without
networking, real keys or application data volumes, under non-root users and bounded
CPU/RAM/PIDs. Read-only mounts load the separate module branches together without
copying their production files into the 07 PR. 02 passed **157**, 04 passed **169**
(one existing live embedding test skipped), 06 acceptance passed **137**, and the
complete combined 07 suite passed **76**, including all six strict Free Tier tests. Full Ruff
lint/format and Git whitespace checks pass within all four owned modules.

The 07 Docker run initially found two existing source-provenance tests missing Git;
after the test-only packaging fix, all 76 passed. No skip/xfail hides those failures.
Only the existing opt-in live embedding check in 04 is intentionally skipped offline.
