# Proposed 05 signal sink and timing — 31 October 2026

The merged 02 add_event helper fixes policy_version to chat-local-v1; AnswerResult
is strict and has no 05 signal field. This proposal is not permission to write 02's
private tables or overload its policy version. No 05-to-review-queue publication is
claimed until the owner-02 sink is agreed and implemented.

Proposed payload from review_envelope: schema_version=1, signal_policy_version=
chat-review-draft-v2, source=system_rule, signals with policy_version/reason/source/
confirmed=false. It contains no question, answer, credential, client owner or case status.
02 must bind owner/job/message/frozen sources from its publication transaction, preserve
signal policy separately from moderation policy, and apply the same publication guard
for fresh/cache/retry/resume. Do not persist a case that outlives deleted/expired source
content. Keep user reports, unconfirmed rule observations and admin decisions distinct.
An insufficient-evidence signal never asserts out-of-scope or factual error.

The local corpus now includes quoted translation/meaning, Thai marks, hidden characters,
technical language and override text outside quotes. It is not a human-gold semantic
benchmark, offensive-content classifier or a measured false-positive rate.

Operational logs measure retrieval calls, generation orchestration and total adapter
answer duration, including failed calls. No raw text/errors or provider keys are logged.
Total includes cache hits; retrieval may have multiple entries. They are per-operation
measurements, not p50/p95 or an SLA; queue time remains 02/07's responsibility.

Validation on Windows: 240 full-suite tests passed in 116.90 seconds with warnings as errors; 16 review/timing tests passed separately; whole-module Ruff lint/format passed. No live provider calls.
