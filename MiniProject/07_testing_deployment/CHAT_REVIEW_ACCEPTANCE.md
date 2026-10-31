# Feedback / chat review acceptance — 31 October 2026

Implements module 07's portion of the supplied feedback/chat-review plan. Changes
stay in 07. Its branch first merged `origin/develop` (`b4f97be`), then takes module
02's feedback/0004 contract as an explicit dependency. The 07 PR is stacked on
`feature/02_api_backend`, so its review diff contains only 07 files. Merge 02 into
develop first; retarget 07 to develop afterward. No PR is auto-merged by this task.

## Coverage

- Versioned 32-case **synthetic** Thai/English corpus: direct abuse, threats,
  mild warnings, attempted rule bypass, hidden Unicode, full-width text, selected
  repeats/spacing, Thai similar words/tone marks, quoted study context and abuse
  outside quotes. These are explicit rule expectations, not human-reviewed video gold.
- Independent auth/API cases: idempotent dislike/details, current feedback after
  login/history reload, cross-account denial, CSRF, suspended sessions, capability-
  gated audited admin access, exact job/message pairs, original source/citations,
  history erasure and no readable review copy. A nonempty consumed reservation
  with 123 synthetic tokens survives deletion unchanged; no real ledger is touched.
- Actual 02/03/04/05/06 domain composition with local caption/embedding/model
  doubles: published, withheld and insufficient-evidence outcomes; original evidence
  versions and exact pair IDs; cold paired SQLite/Chroma backup/restore preserves
  message IDs, visibility and feedback. Insufficiency/dislike is never automatically
  treated as an admin-confirmed out-of-scope problem.
- Added browser scenario creates a real answer through the current 01 UI, then
  sends feedback through real cross-origin browser `fetch` with session and CSRF.
  It exercises PUT/PATCH/DELETE CORS, repeated writes, history reload, other-account
  denial, logout 401, admin pair/scope/review, withdrawal and history deletion.
  Only external Google GIS is doubled; API routes are not mocked.
- Existing real-HTTP identity/research scenarios remain in the runner. Test-only
  review capability is granted solely to the already-seeded `fixture-admin` in an
  isolated test database. New `CHAT_REVIEW_`/`MODERATION_` environment settings are
  scrubbed by the shared test environment builder.
- Existing legacy migration/restore gate now expects revision 0004. Migration
  preservation, empty downgrade and refusal of populated destructive downgrade
  are additionally tested in module 02.

## Measured validation

- Full 07 suite on Windows host: **120 passed**.
- Full 07 suite in Linux Docker, `-W error`, network disabled: **120 passed**.
  Built `video-buddy-07-feedback:test` from the locked test target. The final 02
  source and 07 tests were mounted read-only, with explicit source PYTHONPATH.
- Real-HTTP browser runner: **10 passed**, cleanup passed, no API route mocks or
  paid provider calls. Evidence: ignored
  `runtime/browser-identity-d1af24e873/{report.json,browser.log}`.
- Module 02 integration/full consumer tests: **47 passed**; 04 evidence-library
  regressions **12 passed**; 06 video-learning regressions **23 passed**.
- Ruff lint/format: **305 Python files** pass; changed browser test passes Prettier.
- Backend guard suite: **24 passed**, including legacy completed-message ID lookup,
  guarded resume and an abusive suffix beyond 12,000 characters. Final full backend
  Docker run: **182 passed**, using the final source/tests mounted read-only.

Docker runs use non-root image users, `--network none`, CPU/memory/PID caps and no
real credentials, account database, application data volume or quota reset. Initial
02 container execution hit one transient fixture import/lease setup failure under
load; a full rerun passed 179, then 181 after added regressions. No test was skipped
or assertion weakened to resolve it. The final backend run covers the final source.

## Local latency baseline

`scripts/chat_review_benchmark.py --checkout --output <07/runtime/report.json>`
builds a temporary database with **1,000 synthetic question/answer pairs**, 1,000
feedback rows/cases. Each measurement has 40 samples; page size is 20 and includes
audit writes. Actual nearest-rank p50/p95 on this Windows machine under concurrent
test load:

| Scenario | p50 ms | p95 ms |
| --- | ---: | ---: |
| Entire 32-case local rule batch | 0.31 | 0.47 |
| Authenticated HTTP review page, escaped search | 46.23 | 95.21 |
| Idempotent feedback HTTP PUT | 9.27 | 10.95 |

Evidence: ignored `runtime/chat-review-benchmark-final.json`, source digest
`26f44a994469e7e0cbfe853af046561a513e3437f916d2958a712e494d05e55f`.
This is a baseline, not a speed improvement, production-concurrency benchmark,
per-message p95 for the batched corpus, or model-response latency. Provider calls: 0.

## Remaining owner integration / acceptance

Module 01 still owns new feedback controls in full/floating/history, user notice,
warning-confirmation UI, admin review tab, failed-save rollback/retry display and
accessible responsive layouts. This PR tests browser/API contracts through the
current UI; it does not claim those new controls exist or pass visual acceptance.
New-feature screenshots remain pending module 01's implementation; fabricating a
mock screen would not validate the deployed integration.

Module 05 still owns semantic evidence-only/out-of-scope reasons and corresponding
policy metadata; 02 currently preserves existing insufficient-evidence status and
adds explicit visibility for a withheld placeholder. No automatic semantic verdict,
ban, model training, extra classification model call or human-gold score is claimed.
04 needs no new metadata and 06 has no changes in this MVP.

Review content capability stays off by default until the notice is deployed, then
requires both an active admin and explicit ID allowlist. Expiring drafts are hidden
on reads and anonymized by the worker sweep/operator purge; rollout requires the
usual stopped paired backup and migration. GitHub CI results for the committed
combined branch are linked in the PR; no statement here claims a new merged release.
