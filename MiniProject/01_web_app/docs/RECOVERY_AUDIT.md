# Workspace recovery audit — 26 October 2026

## Fixed in module 01

1. Starting a new conversation clears the previous task error, retry flag and new-result indicator in both chat surfaces. Saved server history is not deleted.
2. An invalid duration entered for a study plan no longer blocks a later summary, comparison, quiz or flashcard request. Duration is validated and submitted only for tasks that use it; the backend retains its own validation.
3. When status polling has stopped, a confirmed cancellation/failure releases the associated composer. A cancellation request that still returns `running` does not prematurely unlock it. Active pollers retain their existing completion path.
4. Active channel/date filters remain visible on the home page. The selected count now also reports how many selected sources match those filters. Both chat composers explain an empty intersection and prevent submission; comparison explains its two-source requirement. Selection and backend scope filters are preserved.
5. Import rejections use actionable Thai messages instead of raw error codes. Deletion failures identify the failed action without exposing provider details.
6. A terminal job state takes precedence over stale processing-stage/retry metadata. Successful imports still distinguish ready sources from videos without captions.

## Validation

- 113 unit tests passed, including terminal status precedence.
- 92 standard browser tests passed; 8 integration-only tests were skipped by that default command.
- The separate real HTTP identity harness passed 8 tests against an isolated API/worker/database using `HttpSessionPort`. `/api` routes were not mocked; external Google/Gemini behavior used fixtures. These tests do not certify live Google or Gemini service access.
- Recovery tests cover conversation reset, hidden duration, cancellation after polling failure, running cancellation not unlocking early, filter recovery, and rejected import copy.
- TypeScript/production build, formatting, diff whitespace check, and production authentication-gate smoke passed.
- Live localhost inspection confirmed session restoration, private library rendering and the new selection guidance in full/floating chat.

## Remaining runtime dependency

The live runtime reports `gemini_free_policy: unverified`. No operator Free Tier policy file was configured during this audit. A missing worker was restarted; the pending analysis reached a terminal `free_tier_unverified` failure rather than remaining queued. This is not a successful AI answer.

No model switch, billing change, Free Tier attestation, credentials edit, private-data deletion or outbound Gemini test was performed. A verified operator policy and subsequent live acceptance are still required. The localhost services are development processes, not a persistent deployment supervisor.
