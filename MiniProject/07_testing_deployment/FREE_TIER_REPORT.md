# Free Tier / visual verification report — 25 October 2026

**Not release accepted.** Module 07 changes are confined to 07 and the authorized
root workflows. Work began from actual develop `1814bf3622eb62f0963da4f682ea31661728907c`
in a separate worktree; no 01–06 source or user store was changed. PR22 was already
merged. This is a new PR for the Free Tier preparation plan.

## Changes

- Added offline, fail-closed Free Tier evidence checking: actual operator confirmation,
  project/key binding, fresh timestamps, model/role/alias/limit match, bounded trial
  budget, exact clean source and reviewed test gates plus matching backend policy.
  `preflight.py --run` rejects before state checks or process launch. The checker never
  contacts AI Studio or claims it independently verified billing.
- Disabled the old live smoke even after a review artifact: its downstream request
  fan-out is not governed by an enforceable end-to-end smoke budget yet. No API key,
  billing, tier, configured LLM_MODEL, provider or paid fallback was changed.
- Kept offline HTTPS/auth/startup drills separate using their exact synthetic key and
  internal-only network. They do not create a release attestation or submit model work.
- Added strict v2/v1-source/citation/vision-provenance and actual 02/05 handoff tests.
  Missing/incompatible features fail explicitly. Baseline regression and manual strict
  feature acceptance remain separate; neither old candidate greens nor skipped tests
  certify new Free Tier features.
- Added pinned local FFmpeg/Tesseract/Thai-English tools, original fixture generation,
  real OCR, sampling, hashes, resource measurements and retained copyright/inventory.
  The default CI QA job runs without networking under non-root CPU/RAM/PID limits.
- Cold backup format 2 includes referenced `state/media/` with SQLite/Chroma; v1 backup
  restores remain accepted. Media corruption is detected before destination creation.
  Empty Chroma directories accepted by state validation now survive backup/restore.
- Added the detailed release matrix and server/rollout/recovery handoff. Frontend
  format remains a strict CI gate after runtime tests so one upstream formatting issue
  does not prevent collecting browser/integration evidence.

## Actual checkout verification

Windows host, Python 3.11.16, uv 0.12.9; Docker Linux/WSL2, frozen pnpm dependencies.
Full native regression logs/JUnit are under `runtime/20261025T025953111267Z/` and
`runtime/full-20261025.log`; final current-head CI artifacts are authoritative for the
submitted merge-test revision. No pinned module overlay was used for these checks.

| Check | Observed result |
| --- | --- |
| Actual checkout Python regression | **721 passed**: 658 upstream/domain + 48 final 07 acceptance + 4 regression + 11 auth; Ruff lint/format passed |
| 07 evidence-gate tests | 24 passed, synthetic attestations only; Paid/unknown/expired/drifted/incomplete reviews and unbounded smoke reject before requests |
| Extra restore regression | v1 format + v2 media tamper/empty-directory case passed; real SQLite/Chroma/image restore is in the 07 acceptance suite |
| Backend auth | 11 passed |
| Frontend | typecheck/build + 90 unit tests passed; production preview smoke passed |
| Existing browser | 66 passed / 8 explicit backend/identity opt-in skips |
| Floating Buddy strict browser | 4 passed |
| Actual HTTP identity/API/worker | 8 passed; external Google/model is fixture, not real provider acceptance |
| Local HTTPS/auth containers | Passed with synthetic key, private network and cleanup; real Google/public HTTPS/release attestation false |
| Frontend format | **FAILED** `01_web_app/tests/domain.test.ts`, including `--end-of-line auto`; not a Windows CRLF-only difference. Outside 07 edit scope; retained strict failure for 01 owner |
| Strict new feature gate on actual develop | **1 passed / 5 failed**: evidence_v2/quota modules not yet merged. Not skipped or counted as accepted |
| Unreviewed Free Tier CLI | Release ready=false, no provider request; CLI refuses acceptance |

Initial real-identity attempt hit the occupied browser port while another browser
suite was running. It cleaned up; rerunning sequentially passed all 8. The new simple
backup fixture exposed empty-directory loss; fixed in 07 and rerun passed. Neither
attempt is represented as a successful first run.

## Real local tool drill

`Dockerfile.media` built and ran on this Windows host through Docker Linux containers,
non-root with no network, 1 CPU, 512 MiB memory/swap bound, 128 PIDs and read-only root.
Seven original 2-second/640x360 clips and 14 sampled frames completed. Clear English
`TEA SHOP` and Thai `ร้านขายชา` were read by actual Tesseract.

Measured serial case totals: **7.095 seconds wall / 6.572 seconds child CPU**; cumulative
peak child RSS **93,072 KiB**; generated artifacts **1,186,061 bytes before report.json**.
These are local tiny-fixture measurements, not the owner's real server capacity.
Actual tool versions, language model hashes, clip/frame hashes, timestamps, OCR output,
package inventory and license notices are in `evidence/free-tier-2026-10-25/`.

No Gemini request occurred. No model answered these clips. Mixed audio is a synthetic
tone/sidecar caption; the unnamed avatar is geometry. Real spoken-content/face-scene,
prompt-injection resistance and answer quality are still pending. Sampling misses the
brief event by design and reports `whole_video_reviewed=false`. The QA tools are not
silently advertised as an integrated module 03 production worker.

## Isolated comparison of unmerged PRs — NOT develop acceptance

| Module / PR | Exact selected source |
| --- | --- |
| 01 / #28 | `fffbcec5afa574851a6d4992d8ca10c7ae47e294` |
| 02 / #27 | `b3bb18d960cc664653a8d3be4732112f1c1059b2` |
| 03 / #25 | `dfda16d3b1bd1d2aae7e9c84780095f5fd201916` |
| 04 / #29 | `b3e983a30a4677b7f344bb09af013fd2cac4f9af` |
| 05 / #26 | `387dfeddb7f5f7db91f455c12ec4b5db67ed855b` |
| 06 / #30 | `e63bdb65021e7865b4ed5fc7905264367aeacef4` |

Generated only under ignored `07/runtime/candidate-989b9c8fa7`. The original 07 lock
check **failed** because 03 adds Pillow. For this diagnostic only, explicitly resolved
the isolated candidate lock (Pillow 12.3.0); default 07 lock was not changed. Both old/new
lock hashes, test source hash and the diagnostic lock are retained in the evidence
directory. Do not report this as passing the original frozen-lock check.

The real 02 quota/media test files passed **24 cases**, including process reservation
races, revocation, role/alias fences, usage reconciliation, visual publication and
private media/migration behavior. The strict 07 comparison passed **5 schema cases**
but **failed 1 actual consumer handoff**: 05's `verified_grant()` calls `authorize()`;
02's execution-bound `QuotaBroker` exposes `access()` and `ExecutionContext.gemini_call`
instead. No compatibility adapter was invented in 07. These results do not prove that
chat/embedding/vision/agent share one working broker across the combined application.

To replay, use `candidate.py --manifest` with the recorded JSON, inspect the initial
lock-check failure, explicitly copy the retained diagnostic lock only into that new
candidate's 07, then `uv sync --locked` and `check.py --group free-tier`. For the 02-only
comparison use its `tests/test_free_tier.py` and `tests/test_media_v2.py` under the
runner's cleaned environment. Never copy candidate modules over default checkout.

## Remaining release blockers

01 owns the formatting defect and real v2/pause browser integration. 02/05 must align
broker semantics; 03/04/05/06 need a tested producer/retrieval/model/agent route with
every real outbound request covered. Actual v1 history/owner comparisons, migration
of the combined stores, visual-only chat, request-count cache assertions, server
capacity/retention/metrics and image-bound deployment attestation remain incomplete.
The current Gitless runtime image cannot satisfy clean checkout evidence; no bypass
was introduced. Host/source review is not a substitute for that image gate.

No private AI Studio project/key/tier or model quota has been checked. Keep real Gemini
off, continue offline/local OCR, and keep the PR Draft. Real Google login/public HTTPS
and live model quality remain separate pending checks. See FREE_TIER_ACCEPTANCE.md
and LOCAL_MEDIA_TOOLS.md for exact commands, expectations and operational limits.
