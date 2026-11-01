# Free usage phases — 2026-11-01

Develop `9aca742` was merged before changes. This increment changes only module 02.

## Calendar accounting and recovery

Admission RPD uses midnight-to-midnight `America/Los_Angeles` through `zoneinfo`.
RPM/TPM, countTokens' separate budget, member fairness, leases, dispatch fencing and
provider Retry-After circuits remain enforced. Existing ledger rows are retained;
no policy limit or billing attestation is increased, reset or fabricated.
`requests_24h` remains an actual rolling usage view for existing clients. New
`requests_provider_day`, `daily_reset_at`, `daily_timezone`, and admin-only
`remaining_requests_provider_day` describe calendar admission. These remain local
accounting, never a verified Google balance. Held reservations crossing midnight
still reserve capacity; sent/uncertain calls retain their actual dispatch date.

Explicit resume follows committed replacement chains and preserves frozen sources.
New jobs pin the configured provider/model/version in private execution metadata;
resume and outbound admission reject configuration changes rather than silently
changing providers. Older jobs without this pin retain their Gemini route.

## Local receiving boundary

`ExecutionContext.local_inference()` supports private Ollama `/api/chat` and
`/api/embed`. Configuration is server-owned, generation defaults to Gemini, local
concurrency defaults to one. Configure `GENERATION_PROVIDER=ollama`, `LOCAL_MODEL`,
`LOCAL_MODEL_DIGEST` (64 hex digest from `/api/tags`), `LOCAL_BASE_URL` (loopback or
private Docker service), `LOCAL_CONTEXT_TOKENS`, `LOCAL_MAX_OUTPUT_TOKENS`.
Local embedding separately requires `EMBEDDING_PROVIDER=ollama`, `EMBEDDING_MODEL`,
`LOCAL_EMBEDDING_MODEL`, and `LOCAL_EMBEDDING_DIGEST`.

Local attempts use the existing durable reservations table under `local:ollama`,
which is outside the allowed Gemini project identifier alphabet. No Gemini grant,
key or RPD is needed. Duplicate call keys and capacity are checked in the same
serialized database transaction as the current lease/member check. Model digest
is checked before sending a prompt and after receiving output. Responses are
bounded, redirects/proxies are disabled, embedding truncation is disabled, and
incomplete generation is rejected. Errors are sanitized; no alternate provider
is called. Cancellation stops client transport, but does not prove that a server
has already stopped GPU computation; configure Ollama concurrency too.

`ExecutionContext.checkpoint(key, value)` stores up to 512 KB of adapter-private
JSON in the lease-fenced job payload. Replacements inherit it with frozen request,
sources and execution identity. Adapter consumers must include the complete input
and model identity in checkpoint keys and revalidate citations before publication.

## Integration and acceptance boundaries

This hook is not a public model proxy and does not mount module 05 generation or
module 01 provider controls. Those owners must explicitly integrate it before a
whole-web local release. Use module 06's local-aware factory for its own tools.
Run Ollama with cloud disabled (`OLLAMA_NO_CLOUD=1`), no public port, and an
operator-reviewed installed local model. This change does not download models,
change an operator's `.env`, migrate a real DB, install policy or reset quota.

Human-gold remains pending. Mock local HTTP tests verify mechanisms, not Thai
semantic quality, real-model capacity, real Google remaining quota or rollout.

References checked 2026-11-01:
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://docs.ollama.com/api/chat
- https://docs.ollama.com/api/embed
- https://docs.ollama.com/api/tags
