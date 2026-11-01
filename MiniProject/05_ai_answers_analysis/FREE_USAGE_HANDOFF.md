# Free usage plan — module 05 — 1 November 2026

## Phase 1

`AnswerAdapters.answer/analyze` now emit one content-free operation summary with
duration, outcome and actual `countTokens` / generation dispatch-attempt counts.
Counts include the native-video path, exclude denied reservations, and are isolated
between concurrent asyncio operations. A failed/timeout dispatch is still an attempt,
not proof of provider billing. Retrieval/generation timings remain separate logs.
No questions, answers, keys or upstream exception strings are recorded.

The existing ordinary grounded-answer path uses one generation when evidence is
sufficient (regression tested). Additional evidence is read only after insufficient
evidence; the bounded context retry remains. Cache keys already include owner,
frozen sources, relevant history, settings/prompt/retrieval configuration and model
allowlist. Hits recheck access; history reads do not generate answers. Companion
greetings already have a system path. No quota policy/count reset was made here.

## Phase 2 foundation, explicitly not enabled

`youtube_answers.local.LocalSettings` and `OllamaModel` implement the existing
`generate(payload, timeout)` interface for text-only AnswerService use. Use an
explicit installed model name, literal loopback host and port; environment proxies
and redirects are disabled. Set Ollama's `OLLAMA_NO_CLOUD=1` at service startup.
No model is downloaded and there is no fallback to Gemini or remote endpoint.
The same answer JSON schema and downstream evidence/citation validation apply.
Input + output budgets are checked conservatively before dispatch; truncated,
tool-call, changed-model, malformed and oversized responses are rejected.
One bounded request; cancellation propagates. Metadata records `provider=ollama`,
configured/returned model, observed usage and elapsed time. No streaming partial
answer is published or attached to feedback.

Example for a controlled benchmark (not a production factory configuration):

```python
model = OllamaModel(LocalSettings(model="<installed-local-model:tag>"))
service = AnswerService(answer_settings, model, authorized_knowledge)
# Call using frozen authorized sources and the existing execution context.
# Always await model.close() when finished.
```

Neither production factory mounts this experimental model. Module 02 must first
provide frozen provider/model/version routing, bounded local resource admission,
health/loading state, local-aware retry/resume and cache publication contracts.
Module 04 must provide a separate versioned local embedding index. Module 06 owns
learning-tool local generation; this adapter does not replace it. Do not label the
whole application local while embeddings/agent still require Google.

## Acceptance still required

Observed development hardware: 21,246,033,920 bytes RAM, NVIDIA MX130 reported 2 GiB
VRAM plus Intel UHD; no Ollama executable found on PATH. This is not a benchmark.
No model selected/downloaded; model licence, Thai human-gold comparison, cold/warm
latency, peak memory, concurrency and hallucination/injection evaluation remain open.
Mock HTTP tests prove adapter/error/citation behavior, not model quality or throughput.
No live Gemini calls, real user database migration, billing change or deployment.

API reference: https://docs.ollama.com/api/chat (structured format, non-streaming
response, done reason, model and usage fields; checked 1 November 2026).
