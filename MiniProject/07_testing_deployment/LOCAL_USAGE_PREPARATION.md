# Free usage phase 1/2 evidence — 2026-11-01

Owned scope: 02/04/06/07. Develop `9aca742` was merged into each module branch
before editing. Previous PRs 43/44 and integration 49 are merged; prior review
constraints (strict producer contracts, isolated auth fixtures, no fabricated
attestation) remain in force. No 01/03/05 source files were edited.

## Test evidence

| Suite | Windows | Linux Docker |
|---|---:|---:|
| 02 backend | 221 passed | 221 passed |
| 04 RAG | 178 passed, 1 live opt-in skipped | 178 passed, 1 live opt-in skipped |
| 06 agent | 161 passed before citation enum increment | 161 passed before final metadata/enum increments |
| 06 final local boundary | 9 passed | 9 passed |
| 07 complete suite | 136 passed | 136 passed |

Warnings are errors. Docker uses installed locked test images with current source
mounted read-only and explicit PYTHONPATH, network disabled, memory/CPU/PID limits.
These source-mount tests do not replace building the new dependency lock in CI.
Ruff passes for all owned modules. Compose local configuration parses with a pinned
image. No production Compose service, DB or migration was started.

Focused actual API/worker test uses a temporary real SQLite DB, authenticated
members, real RAG/domain/broker code, synthetic captions and synthetic Ollama HTTP
responses. It verifies publication, idempotent replay, old-result reads without
new model calls and 404 access for another member. Existing broker tests cover
unsent/uncertain requests, 429/timeout, cancellation and worker admission; new tests
cover Pacific DST/calendar boundaries and local capacity/provider pinning.

## Host and actual model experiment

Read-only host inventory: RAM 16,557,793,280 bytes, NVIDIA RTX 3050 Laptop GPU with
4096 MiB, D: free space about 229 GB. No host Ollama installation was found.
`local_preflight.py --probe` reports unavailable, not ready, zero model calls.

Experiment uses an isolated Docker model volume `vb-local-probe-models-20261101`,
Ollama Linux amd64 image digest
`sha256:93c1376d651a9f1579ee40cc5763852f08b204466371e4bb64bca2a1d8d08e2d`,
CPU only (GPU not passed through), 3 GiB / 3 CPUs, concurrency one, cloud disabled.
Downloads occurred in a dedicated temporary service without application data.
Inference service uses an internal Docker network with no published ports or
external network, separate from all existing databases.

Trial models (not selected production defaults):
- qwen3:0.6b, digest `7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435`.
- qwen3-embedding:0.6b, digest `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`.

First real-model probe: synthetic transcript indexing completed in 8.94 s, one
real embedding request; flashcards/quiz/study plan were correctly rejected for
invalid citations (22.71/14.48/12.79 s), three real generation requests, zero Gemini.
Idempotent retries returned the same job. This failure caused a module-06 fix:
constrain JSON citation arrays to actual supplied IDs without relaxing publication
validation. Follow-up results are recorded in the final PR evidence.

Raw reports live under ignored `runtime/local-*.json`. `local_model_probe.py`
reproduces the experiment with actual models but synthetic identity/captions and
temporary state. It never certifies real-YouTube or human semantic acceptance.

## Repeatable local service and rollback

1. Preserve stopped paired DB/Chroma/media/config and immutable runtime image
   before any production migration, following the 02 rollout runbook.
2. Review Ollama image/version licence and each model's licence, disk size and
   hardware suitability. Model tags can move; pin the measured full digest.
3. Start only the private `compose.local.yaml` profile with `OLLAMA_IMAGE` pinned.
   It has no ports, cloud disabled, bounded CPU/RAM, queue four, parallelism one,
   one loaded model. Provision reviewed models before joining the internal network;
   no automatic model pull or shell-install script runs from backend requests.
4. Attach only the backend worker to the private inference network; browser users
   must use authenticated backend endpoints. Do not expose Ollama directly.
5. Run preflight, then the opt-in local probe on a disposable paired state copy.
   Configure exact generation and embedding model/digests, dimensions, context and
   output caps. Keep Gemini policy/config separate and default route unchanged.
6. Test service-off, restart, queue, timeout, cancellation and rollback on the copy.
   Drain work before changing provider. Frozen old jobs reject changed execution
   identity. Restore old config/image and paired state to roll back index changes.
7. Start the full web only after owners 01/03/05 mount compatible provider routing,
   user-visible selection and status. No hidden Gemini fallback is allowed.

Do not infer capacity from this single-user CPU probe. Cold/warm controlled series,
peak GPU/host memory, concurrent users, fairness under load, real YouTube ingestion,
Thai retrieval/grading accuracy, local-vs-Gemini comparison and production cutover
remain pending. Human-gold stays **pending** by explicit user instruction.
No public rollout, quota reset, paid API or billing change is claimed.

References checked 2026-11-01:
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://docs.ollama.com/api/chat
- https://docs.ollama.com/api/embed
- https://docs.ollama.com/faq
- https://ollama.com/library/qwen3:0.6b
- https://ollama.com/library/qwen3-embedding:0.6b
