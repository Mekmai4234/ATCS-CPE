# Review signal policy compatibility — 31 October 2026

Review #46 identified that the merged owner-02 AnswerReviewSignal receiver accepts
chat-review-draft-v1 only. The original proposal's claim that no sink exists is now
obsolete: ExecutionContext.review_signals stages private attempt-bound observations.

Public review_signals and POLICY_VERSION retain the EXACT legacy v1 rule behavior,
including its treatment of quoted instruction text. They are accepted by the real
receiver; changed quote-aware v2 behavior is NOT relabelled as v1.

review_signals_v2 and POLICY_VERSION_V2 explicitly expose the experimental quote-aware
policy. review_envelope produces that proposed v2 envelope. Never pass these outputs
to the v1 sink until owner-02 supports a coordinated version upgrade, retained-v1 reads,
serialization/admin display, and owner-07 publication-path regression. This PR edits
neither receiver literals nor other modules' tests and does not mount a new producer.

No signal establishes semantic error, out-of-scope content, user fault or a confirmed
admin decision. Quote-aware corpus tests use the explicit v2 interface. A v1 compatibility
test validates real helper output against AnswerReviewSignal and preserves original
quote behavior. Existing evidence-only prompts/publication guards remain unchanged.

Operational retrieval/generation/total timings stay content-free and per-operation;
no p50/p95, SLA or live-provider quality claim is made.
