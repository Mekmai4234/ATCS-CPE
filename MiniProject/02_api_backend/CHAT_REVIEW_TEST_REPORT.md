# Feedback / chat review verification — 31 October 2026

Worked on `feature/02_api_backend` after fetching and merging `origin/develop`
(`b4f97be`, already up to date). Scope: module 02 only. No real user state migration,
provider request or shared quota reset was performed. Contract/rollout details:
`CHAT_REVIEW_CONTRACT.md`.

## Verified behavior

- Additive 0003 → 0004 migration keeps original Thai message content. Empty downgrade
  works; populated moderation/feedback/review storage refuses destructive downgrade.
- Message IDs agree between chat 200, polled result and history, including completed
  jobs created before the new result field existed. Exact question/answer pairing is
  by job ID, independent of clock ordering and retry proximity.
- Feedback is member-private, CSRF protected, unique/idempotent, editable/withdrawable,
  durable in history and unavailable on user messages or withheld placeholders.
- Admin stats do not gain private content access. New review routes require the
  notice rollout flag, active current admin role and explicit capability ID list.
  Excerpts/details/context/review changes are audited without copying chat into logs.
- Direct API and repository input checks run before enqueue; worker rechecks queued
  chat before the answer adapter. Warning acknowledgement is server-bound to owner,
  exact request, policy and expiry. Expired/wrong-owner/edited-text proof fails;
  resume requires fresh acknowledgement and cannot bypass a block.
- Abusive output never enters public job/history. The neutral persisted placeholder
  carries explicit withheld visibility and cannot be rated. Restricted drafts expire
  and become unreadable before the sweep; purge anonymizes their event and deletes
  review notes. Entire bounded output is checked, including long abusive suffixes.
- Owner history deletion erases chat/review copies while keeping content-free durable
  job identities and quota reservations. Independent 07 coverage verifies a nonempty
  consumed reservation survives with its original 123 synthetic tokens.

## Results

- Windows host: full backend suite **179 passed**, then expanded focused guard suite
  **24 passed** (adds legacy-result/resume/long-output regressions).
- Linux Docker: final full-source run **182 passed**, including the long-output
  regression (earlier successful runs: 179, then 181). Network disabled, non-root,
  memory/CPU/PID caps;
  latest source/tests mounted read-only on the freshly built locked test image.
- Combined consumer checks on the dependent 07 branch: backend integration/full
  **47 passed**; 07 host/Docker **120 passed**; real-HTTP browser **10 passed**;
  04 library **12 passed** and 06 video learning **23 passed**.
- Ruff lint/format pass; combined check covers **305 Python files**. Changed browser
  test passes Prettier. Synthetic Thai/English 07 corpus: 32 explicit rule cases.

The first Docker run hit one transient fixture import/lease setup failure under
concurrent load (178 passed/1 setup error). It was rerun in full without skips,
assertion reductions or quota changes, producing the successful counts above.

Latency is a local synthetic baseline, not a speed improvement: 1,000 pairs, page
size 20, n=40; review HTTP p50/p95 **46.23/95.21 ms**, idempotent feedback HTTP
**9.27/10.95 ms**. Exact raw report/source fingerprint is in 07's acceptance report.
No live AI semantics, production capacity or new UI acceptance is inferred.

## Delivery boundaries

02 PR targets develop. The separate 07 PR is stacked on 02 and contains only 07
changes; merge 02 first, then retarget 07 to develop. The combined branch includes
the 07 migration gate's schema expectation update from 0003 to 0004. The old 07
test still hardcodes 0003 on the standalone 02 head; report that shared gate
separately rather than mislabeling it as a new backend failure or skipping it.

No PR is merged by this task. GitHub CI links/status are reported in the PRs.
New feedback/admin/warning UI, notice rendering and screenshots remain with 01;
semantic out-of-scope reasons remain with 05. No new metadata is needed from 04,
and 06 has no changes for this MVP. Admin review access stays disabled by default.
