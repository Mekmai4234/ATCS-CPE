# Integration / rollout preparation — 31 October 2026

Worked on `feature/02_api_backend` after merging current develop `372f136`.
That develop CI (41177980439) completed all five jobs successfully; the old review
findings are accepted/merged, and this round is new integration preparation.

Changes only in 02:

- Typed opt-in receiving contract for actual 05 `review_signals` dataclasses. Explicit
  producer/source/draft policy is separate from `chat-local-v1`; unknown versions,
  verdicts, out-of-scope claims and raw text fields are rejected.
- Private, deduplicated staging under current job/account/source/lease authorization.
  Only current-attempt metadata becomes a new unconfirmed case in the assistant
  publication transaction. Prior attempts/cancelled work cannot publish stale signals.
  Existing citation validation and withholding still decide answer disposition.
- Signal metadata is available only on capability/audit-protected admin detail, with
  explicit no-publication-effect and distinct answer visibility. Nothing is added to
  public chat/job/history/progress or the strict 05 answer response schema.
- Uses existing event/case columns; deployed migration 0004 is unchanged. No provider
  call, key switch, ledger reset, role grant or production migration is performed.
- Current UI handoff table replaces ambiguity about proposed endpoints with actual
  IDs, reason codes, CSRF, replay/resume errors and withheld/expiry behavior. 01 owns
  updating its old handoff and mounting the components.
- Operator runbook covers stopped paired backup, 0004 migration, disabled-by-default
  startup, original media/database namespace, notice-before-capability, purge scheduling,
  owned-account smoke and rollback by restore rather than populated downgrade.

Validation:

- Full backend on Windows host: **197 passed**, `-W error`.
- Full backend on Linux Docker: **197 passed**, `-W error`, no network, resource caps,
  non-root, current source/tests mounted read-only on the locked test image.
- New receiver/privacy/attempt tests: **10 passed**. Dependent 07 actual-producer
  helper/cache/retry/resume integration: **3 passed**, with local model/policy fixtures.
- Combined 07 host/Docker: **133 passed each**; real-HTTP browser: **10 passed**,
  cleanup passed; no API mocks or paid provider requests. Migration drill preserves
  actual fixture feedback and a nonempty synthetic ledger through purge/cold restore.
- Ruff lint/format pass. New exact-branch CI is linked/statused in the PR; a prior
  merged develop pass is not described as certification of new code.

This is the receiving side, not automatic 05 producer mounting or 01 UI integration.
The user confirmed no human-gold dataset; keep that and live-model semantic accuracy
pending. No new-feature screenshots are claimed before mounted UI exists. Review
capability remains OFF by default. 04/06 need no change in this feedback MVP.
