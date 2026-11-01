# Free usage learning workflow — 2026-11-01

Develop `9aca742` was merged before work. Depends on owned 02/04 receiving
boundaries; no source changes to modules 01, 03 or 05 are included.

`AgentSettings` consumes explicit `GENERATION_PROVIDER=ollama`, `LOCAL_MODEL`,
`LOCAL_MODEL_DIGEST`, `LOCAL_CONTEXT_TOKENS`, `LOCAL_MAX_OUTPUT_TOKENS` from the
resolved backend settings. `youtube_agent.integration:create_adapters` now selects
the local model explicitly and declares its local research/artifact operations.
Gemini remains the default and is never called as an automatic local fallback.
The standalone 06 factory still does not supply module 03 ingestion or 05 analysis.
Full team mounting needs those owners' integration; do not silently switch an old
05 factory's configuration to claim that it is local-aware.

Local generation uses schema-constrained JSON, the same artifact validation and
citation checks, bounded untruncated inputs, timeouts and backend-owned durable
admission. Metadata identifies `ollama` / `ollama-cache` and the returned digest.
Research uses ordered authorized evidence pages then one structured synthesis;
the local model never chooses or executes tools. Step/input budgets can produce
an explicitly partial result. Native video/vision is not added by this adapter.

Learning artifacts checkpoint their generated structured content with complete
request, source versions, full evidence, schema and non-secret generation settings.
A retry/resume rereads authorized evidence, uses an identical checkpoint only,
revalidates schema/quality/citations and publishes through the existing worker fence.
Cached calls have zero new usage and latency, and disclose their cache provider.
Local structured generation has a second model/digest/input-bound checkpoint for
worker restart. Checkpoints are private and copied only with frozen replacement jobs.

The local grading adapter accepts server-provided questions/reference answers and
student answers, asking for Thai paraphrase equivalence and rejecting invalid JSON.
Existing 02 quiz admission/publication still owns blank/count/idempotency validation
and score computation. The 06-only factory does not yet expose a quiz-grade operation;
the full 05 team factory must explicitly mount its local-aware agent before release.
Actual Thai grading accuracy remains unverified; fixture output cannot certify it.

Still pending: arbitrary native research decision checkpoints and restoration of
partially completed multi-tool research, local summary/compare via module 05,
owner-01 provider/error presentation, human-gold, real installed-model quality,
restart/capacity measurements and a coordinated rollout. No real provider calls,
key rotation, quota reset, billing change or real DB migration was performed.
