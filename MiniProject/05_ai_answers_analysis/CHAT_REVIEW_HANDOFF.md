# Chat review handoff — 31 October 2026

This PR supplies a local, draft-versioned review-signal API; it is not mounted on
public results and is not a complete moderation engine. No AI call or raw-text log
is introduced. Signals distinguish insufficient evidence from an unproven out-of-scope
claim. Missing citations and possible instruction override are unconfirmed system-rule
signals, not user reports or admin conclusions. Original text and Thai marks stay intact.
The existing evidence-only prompts/citation validation remain active and unchanged.

02 must agree and version the policy, input acknowledgement/expiry, pre-enqueue guard,
pre-publication disposition and withheld-draft storage with audit/retention before wiring.
The worker must gate fresh, cached and retried answers before publishing any draft.
01 must show neutral withheld-output messages without feedback buttons. 07 needs a
reviewed Thai/English false-positive/negative corpus; this small rule set is not that corpus.
No response-schema fields, private access capability, moderation events or suppression
behavior are invented in 05. Never infer out-of-scope solely from no retrieved evidence.

Pending: agreed offensive/quoted-content policy, full input/output guard integration,
publication of versioned events via 02, retained published-versus-withheld distinction,
real member/admin E2E, semantic review and latency measurements.


## Remaining-work increment

See REVIEW_SIGNAL_CONTRACT_PROPOSAL.md for the separately versioned v2 envelope,
quoted-study corpus and operational retrieval/generation/total timings now instrumented
in existing adapters. The envelope itself remains unmounted: current 02 add_event
hard-codes chat-local-v1, so owner-02 acceptance is still required before queue integration.
Do not treat pending sink agreement as completed publication-guard integration.


## Review correction after #43/#44 merged

The receiver now exists. Public review_signals preserves the exact legacy v1 behavior;
quote-aware v2 is explicitly review_signals_v2 and remains experimental. Do not send v2
to the v1 sink or relabel its changed rules. See REVIEW_SIGNAL_CONTRACT_PROPOSAL.md.
