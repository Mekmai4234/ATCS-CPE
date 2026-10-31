# Producer 05 → backend 02 contract — version 1

This is the 02 integration boundary for the existing 05 `review.review_signals`
helper. It accepts its current `chat-review-draft-v1` metadata. The 05 owner must
opt in from its adapter; this PR does not edit/mount any 05 code or infer a human
agreement from a passing contract test. No new table/migration or public answer
schema field is introduced; deployed migration 0004 is unchanged.

After obtaining a candidate answer (including a cache hit), a trusted adapter may call:

```python
context.review_signals(
    review_signals(
        question=request["question"],
        answer=result.answer,
        status=result.status,
        citation_count=len(result.citations),
    )
)
```

Call this on every returned path, outside any fresh-only/cache-only branch. It is a
server ExecutionContext method, not an HTTP endpoint or client request field. It
checks the current job lease, deadline, account/source authorization and chat target.
Arrays/tuples of at most three dataclasses or dictionaries are accepted:

| Field | Accepted value |
| --- | --- |
| contract_version | `answer-review-signal-v1` (02 wrapper default) |
| producer | `05_ai_answers_analysis` (trusted boundary default) |
| policy_version | `chat-review-draft-v1` |
| source | `system_rule` |
| confirmed | `false` |
| reason | `insufficient_evidence`, `missing_citations`, `possible_instruction_override` |

Unknown fields (including raw answer/question), versions, sources, producers,
confirmed verdicts and `out_of_scope` reasons are rejected. `chat-local-v1` remains
02's separate input/output moderation policy and is not a valid 05 policy version.
There is no automatic out-of-scope or factual-error conclusion and no model call.

Signals stage as private metadata (`moderation_events`, `pending_sig`) with hashed
attempt binding. Identical signals from the same attempt deduplicate. They do not
enter public job progress events, chat/job/history results or citations. Cancelled,
failed, stale-lease and replaced attempts cannot publish their staged metadata as
current cases. An invalid answer still fails the existing citation/schema guard;
staging a signal never permits publishing it. Failed-attempt metadata without a
committed answer is not a review case and expires under the existing retention.

After ordinary validation and the local publication guard, the same SQLite writer
transaction that commits the assistant message promotes current-attempt signals
to new, unconfirmed system cases bound to that exact message/job. Withheld answers
remain neutral placeholders; signal metadata cannot un-withhold them or suppress
an otherwise valid answer. Fresh/cache/retry/resume all share this boundary.

Capability/audit-protected admin detail adds `review_signal` with the table fields
and `publication_effect=none`. Its `confirmed=false` describes the original rule;
the human review outcome is stored separately in `case.outcome`. No signal draft
text is stored. `detail.visibility` describes the answer seen by the user;
`moderation.visible_to_user=false` describes the private signal, not a suppression
of that answer. Notes/event metadata use existing expiry gates and conversation
erasure. Review access stays off until the 01 notice and authorized ID list are deployed.

Producer-side mounting, interpretation of the draft policy, semantic evaluation and
new UI rendering remain explicit 05/01 follow-up work. Do not claim signal production
is enabled merely because this receiving hook exists.
