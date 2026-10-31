# Feedback and chat review — module 02 contract, 31 October 2026

Implements the 02 portion of `Video-Buddy-Feedback-Chat-Review-Plan-2026-10-31.md`.
Only module 02 source/tests/docs change in this PR. The attached proposal is now
authorized for this scope; its earlier “proposal only” label is not a deployment command.

## Storage and rollout

Stop API/workers, take the existing paired SQLite/Chroma backup, then run
`yk-db upgrade head`. Additive Alembic **0004** creates `message_feedback`,
`moderation_events`, `chat_review_cases` and their queue/expiry indexes. Existing
messages, jobs, evidence and shared Gemini accounting stay intact. Empty 0004
tables can downgrade to 0003; populated review data refuses destructive downgrade.
Roll back a populated deployment by restoring its stopped paired backup.
No actual user database is migrated by this change's tests.

Review content access is **off by default**, separately from existing admin stats.
Deploy module 01's user notice first, then set `CHAT_REVIEW_ENABLED=true` and
`CHAT_REVIEW_ADMIN_IDS='["<authorized admin user_id>"]'`. Both an active current
admin role and this explicit capability list are required on every content route.
The policy endpoint supplies the Thai notice, but rendering it remains module 01's work.
There is no new grant-management endpoint or automatic grant to every administrator.

## Stable IDs and feedback (01 handoff)

- Successful chat 200, completed job `result` and persisted history identify the
  same assistant message. Chat/job responses add `assistant_message_id`; history
  retains its existing `message_id`. Older completed jobs resolve the ID from the
  stored assistant row rather than matching by text/time. Current feedback is
  returned by history, chat result, polled result and the explicit feedback GET.
- `GET|PUT|DELETE /api/messages/{message_id}/feedback`. PUT body:
  `{"rating":"dislike","reason":"incorrect","comment":"optional, <=500 chars"}`.
  `rating` is `like|dislike`; reason is optional and one of `off_topic`, `incorrect`,
  `citation_mismatch`, `insufficient_evidence`, `inappropriate`, `other`.
  Like has no reason/comment. GET/PUT/DELETE return `{message_id, feedback}`;
  feedback is null after withdrawal. Details include revision and update epoch.
- One owner/message row, serialized upsert, identical PUT does not advance revision.
  Dislike immediately saves without details; a later PUT saves optional details.
  Changing rating or deleting removes the current user-reported queue entry.
  No feedback call invokes an AI provider or modifies the original answer.
- Only a member's own completed, published assistant answer can be rated.
  User messages, pending work, withheld placeholders and cross-account IDs fail.
  Mutations use existing session/Origin/CSRF checks, including PUT and PATCH;
  CORS now permits both methods. Text remains JSON data; 01 must render with text
  escaping, never raw HTML, and wait for server success before acknowledging a vote.

## Local input/output policy (01/05 handoff)

`GET /api/chat/policy` returns notice, retention and `chat-local-v1` policy version.
`POST /api/chat/check` accepts the same ChatRequest as `/api/chat` and returns
`decision=allow|warn|block`, reason, attempt ID, Thai warning and, for warn only,
an opaque acknowledgement token valid for 300 seconds. To proceed deliberately,
submit the **same question, conversation and scope** with `moderation_token`.
The backend verifies the stored hash, owner, version and expiry; a boolean is not
accepted. Preserve the original text; do not normalize or silently edit the payload.
The token is not stored in the job or returned in history. The repository enforces
the guard even for direct callers. A rejected request has no chat job/provider call.

The worker rechecks input before its answer adapter, including old queued jobs.
A valid acknowledged admission persists a bounded server proof for queued execution.
Explicit resume re-runs admission: precheck the original request again and submit
`{"moderation_token":"..."}` to `POST /api/jobs/{job_id}/resume` when needed.
Blocked or expired acknowledgement cannot be bypassed by retry/resume.

The final serialized publication transaction applies the output guard to chat
answers. Direct abuse is retained only as a restricted, expiring moderation draft;
the public job/message receives a neutral system placeholder, no draft citations,
`visibility=withheld`, and cannot receive feedback. A mildly risky output creates a
**suspected** system case, not an admin-confirmed violation. Published answers add
`moderation_policy_version`. Withheld uses existing `insufficient_evidence` as a
compatible status plus explicit visibility; 01 must hide feedback on this system
placeholder and distinguish it from an ordinary evidence insufficiency.

This is a finite local rule set, not a semantic safety/accuracy guarantee. NFKC,
case folding, format-character removal, whitespace and selected bounded repeat/
spacing patterns operate only on a comparison copy; Thai tone marks stay intact.
Paired quoted material in a meaning/translation question is treated as study
context, while abuse outside the quotes still applies. Sarcasm, dialect, unquoted
study text and unseen obfuscations need human review and more corpus coverage.
No additional model call, automatic ban or training occurs.
The entire accepted output is checked up to a 128,000-character policy bound;
oversized output is withheld rather than publishing an unchecked suffix. Its stored
draft is bounded and explicitly marked truncated. This does not truncate published answers.

Module 05 still owns evidence-only semantics and versioned out-of-scope reasons.
This change does **not** infer out-of-scope from insufficient evidence or dislike,
or add unsupported reason fields to 05's strict answer schema. No new RAG metadata
is needed from 04, and 06/learning artifacts are outside this MVP.

## Explicit administrator routes

- `GET /api/admin/chat-reviews`: defaults to pending (`new|in_review`), SQL
  pagination `limit=1..200`, `offset>=0`; filters `status`, `rating`, `label`, escaped
  `q` in the paired original question, inclusive `after`/`before` epoch timestamps.
  Returns current like/dislike counts, pending/withheld totals and page metadata.
  List rows include a <=120-character question excerpt and pseudonymous member
  reference; each excerpt read is audited. No email/full answer/draft in the list.
- `GET /api/admin/chat-reviews/{case_id}`: exact user/assistant pair by **job ID**,
  frozen source versions, citations, provider metadata, current feedback, label
  source and review state. Blocked input has an attempt case, no invented answer.
  Withheld draft is explicitly separate and marked unseen by the user. All content
  opens are audited; expired text is never returned even before the cleanup sweep.
- `PATCH /api/admin/chat-reviews/{case_id}`: new → in_review → reviewed;
  reviewed requires `confirmed|false_positive|inconclusive` outcome. Notes <=1000
  chars. Reviewer/time recorded; state/outcome audit contains no note/chat text.
  Editing dislike details returns its user-report case to new for review.
- `GET /api/admin/chat-messages` lists paginated assistant IDs without creating
  cases. `GET .../{message_id}` opens the same audited pair contract for normal
  messages; `GET .../{message_id}/context` opens bounded conversation context with
  its own audit. Private conversation endpoints retain their owner-only checks.

## Erasure and retention

`DELETE /api/conversations/{id}` is owner-only and CSRF protected. Cancel running
work first (409 otherwise). Erases messages/citations/feedback/review copies and
job chat payload/history/results, leaving content-free cancelled job identities
for immutable quota reservations; it never deletes/resets the shared ledger.
Blocked attempts linked to that conversation are erased too. Audit rows hold IDs
and actions only, not duplicate chat text.

Rejected inputs/withheld drafts expire after configurable
`MODERATION_RETENTION_DAYS` (1..30, default 30). The long-running worker anonymizes
expired events every 60 seconds and deletes their review cases/notes. When no worker
is running, schedule `yk-db purge-review` externally. Detail reads independently
hide expired content. Ordinary published-message feedback follows original-message
deletion. Backups retain their existing separately controlled lifecycle.

## Validation and remaining integration

Regression tests exercise real FastAPI/session/CSRF and worker paths with fixture
providers, migrations/downgrade refusal, exact pairs, ownership, acknowledgement,
withheld privacy, retention and deletion. Counts and Docker/browser results are
recorded in the PR after completion. Human semantic acceptance and new UI screenshots
cannot be claimed before modules 01/05 implement their portions.
