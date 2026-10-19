# Module 06 — Research and Learning Agent

Python package `youtube_agent` implements a bounded Gemini function-calling loop and
grounded study plans, quizzes, and flashcards. Changes and configuration stay in this
folder. Module 02 owns HTTP endpoints, durable jobs, events, cancellation and storage;
04 owns retrieval, source generations and the persistent knowledge index.

## Install and verify

From `MiniProject`, using Python 3.11–3.13 and uv:

```powershell
uv sync --project 06_research_learning_agent --locked
uv run --project 06_research_learning_agent --locked pytest 06_research_learning_agent/tests -q -W error
uv run --project 06_research_learning_agent --locked ruff check 06_research_learning_agent/src 06_research_learning_agent/tests
uv run --project 06_research_learning_agent --locked ruff format --check 06_research_learning_agent/src 06_research_learning_agent/tests
```

The module lockfile includes local packages 02 and 04. It does not modify their manifests,
lockfiles or source. Tests use isolated temporary SQLite/Chroma data, labelled synthetic
transcripts, deterministic embedding/model doubles and the real GenAI SDK with HTTP mocks.
There are no paid calls or model downloads. The development environment also installs
05 for cross-module acceptance tests, without changing 05's files or runtime dependencies.
See [ACCEPTANCE_REPORT.md](ACCEPTANCE_REPORT.md) for current checks and
[TEST_REPORT.md](TEST_REPORT.md) for the original 55-test baseline.

Docker Desktop must be running with Linux containers. From `MiniProject`:

```powershell
docker compose -f 06_research_learning_agent/compose.test.yaml -p yk06-check build tests
docker compose -f 06_research_learning_agent/compose.test.yaml -p yk06-check run --rm --no-deps tests
docker compose -f 06_research_learning_agent/compose.test.yaml -p yk06-check run --rm --no-deps tests ruff check src tests
docker compose -f 06_research_learning_agent/compose.test.yaml -p yk06-check run --rm --no-deps tests ruff format --check src tests
```

The test container is non-root, has networking disabled, receives an empty Gemini key,
and mounts no application database. Each run is disposable. A Dockerfile-specific build
allowlist excludes local keys, .env files, runtime data and unrelated project files.
Root Compose files are unchanged. This image is a verification image, not a production
deployment of the entire application.

## Configuration

Copy this folder's `.env.example` to `.env` only if no local file exists. Precedence is
process environment > `06_research_learning_agent/.env` > shared `MiniProject/.env` > defaults.

| Setting | Default | Meaning |
|---|---|---|
| GEMINI_API_KEY | empty | Server-side key; required by the live Gemini gateway |
| LLM_MODEL | gemini-3.5-flash | Configurable project-requested identifier; verify access before live use |
| MAX_CONTEXT_TOKENS | 24000 | Application input budget |
| AGENT_MAX_STEPS | 8 | Maximum model decision iterations, including finish |
| AGENT_TIMEOUT_SECONDS | 120 | Maximum total run duration, further limited by 02's deadline |
| AGENT_FINALIZE_RESERVE_SECONDS | 10 | Time reserved for partial output and backend validation |
| AGENT_MAX_OUTPUT_TOKENS | 2400 | Maximum output per model response |
| LLM_TIMEOUT_SECONDS | 60 | Per-operation ceiling, also limited by remaining run time |
| AGENT_READ_PAGE_SIZE | 30 | Chunk page size for direct artifact evidence collection |

The generation model is independent of 04's embedding model. Module 06 does not migrate
existing indexes. No real key is included or needed for offline tests.

The 06-owned `create_adapters` factory now builds AgentSettings and RagSettings from the
backend's already-resolved Settings, so it does not reread conflicting 04/06 env overrides.
Standalone `AgentSettings()` still uses the precedence above. Explicitly injected settings
and the existing 05 team composition retain their own configuration ownership.

## Connection to 02 and 04

```python
from youtube_agent import AgentService, AgentSettings
from youtube_agent.gemini import GeminiModel
from youtube_agent.integration import RagKnowledge

settings = AgentSettings()
model = GeminiModel(settings)
agent = AgentService(settings, model, RagKnowledge(existing_rag_service), analyzer=analyze_05)
# Called from a claimed, current module-02 job; sources are frozen authorized Source records.
result = await agent.research(request, sources, execution_context)
artifact = await agent.artifact(artifact_request, sources, execution_context)
# The application owner must await model.close() and close its RAG service at shutdown.
```

`analyze_05` is optional and has the async signature `(request, sources, context) -> AnswerResult`.
06 checks comparison source IDs and exact intervals; 05 remains responsible for semantic
analysis. With no analyzer, the agent receives the explicit `analysis_unavailable` observation
and can choose another supported action. There is no fabricated comparison fallback.

`AgentAdapters` is an optional 06-owned composition that inherits 04's indexing/deletion/
evidence/inventory methods and adds `research` and `artifact`. Its trusted factory is:

```text
ADAPTER_MODE=custom
ADAPTER_FACTORY=youtube_agent.integration:create_adapters
```

Set these only in the environment of an explicitly configured integration. The package is
available to backend commands when run with `uv run --project 06_research_learning_agent`.
Initialize 02's schema and 04's manifest with the existing `yk-db upgrade head` and
`yk-rag init` commands, targeting an intended development database. Supply 04's compatible
configuration separately as described in its README.

The 06-only default factory leaves 03 ingestion and 05 answer/analyze unavailable.
The existing `youtube_answers.team:create_adapters` factory in module 05 already connects
03/04/05/06, supplies `answers.analyze` to the agent, and shares its RAG instance. Follow
05's integration instructions for that composition; do not replace its configured factory
with the 06-only factory. Existing fixture databases must not be relabelled as live.

## Runtime behavior

The four business tools are `search_evidence`, `read_video_chunks`, `compare_videos`, and
`create_learning_artifact`. A fifth control function, `finish_research`, returns the final
content and known chunk IDs. The controller executes one validated tool per decision.
The SDK's automatic function execution and retries are disabled. Original native model
content, function IDs and thought signatures are retained in memory for the next request;
events contain only concise actions/outcomes, without private reasoning.

Every knowledge call uses 04's `BackendExecution`, which verifies the actual job scope,
source generation/version, lease and lifecycle. The model cannot supply a replacement
owner or widen the selected videos. Unknown tools/arguments are rejected. Identical
repeated actions stop the run. Each await is bounded; cancellation and invalid execution
ownership propagate to 02. Research is not silently restarted after a crash.

Artifacts follow 02's existing schemas. Each study day, quiz question or flashcard has
supporting citation IDs; quiz questions include answers and explanations. Plans have
consecutive days and exactly the requested day count. Citation URLs are constructed from
trusted video IDs/times. 06 re-reads exported citations and checks inventory before delivery,
including partial findings and artifacts retained from previous steps. Changed/missing
evidence or index-configuration failures cannot become a seemingly usable partial result.
02 also revalidates evidence/version/bounds before storing results.

Comparison observations include 05's citation-label-to-chunk mapping and declared coverage.
Tool evidence is checked against the requested subset, not just the larger run scope.
Backend channel/date filters may narrow the original request but cannot introduce videos
absent from its explicit selection.

Coverage counts distinct evidence supplied to a successful subsequent model decision or
validated artifact generation, not merely fetched chunks. This is an operational processing
measure, not proof of semantic understanding. The expected chunk count comes from 04's
real vector inventory. Backend 02 currently requires complete research coverage for
`completed`; otherwise 06 returns `partial`, even for a useful topical answer.

On step/context/time limits, partial research preserves existing artifacts and source
excerpts with explicit limitations. It does not manufacture new synthesis. Finalization
starts before the hard deadline; hard expiry or lost ownership may still cause 02 to record
a failure/cancellation. Terminal `run_controller` events use the last decision step and
actual completed/partial outcome after source revalidation. A proposed finish stays in
`validating` until that recheck succeeds. Cancellation is reported through the durable
job state and never publishes a final result.

## Reproducible quality-review preparation

Run six synthetic Thai/English scenarios in a NEW isolated directory:

```powershell
uv run --project 06_research_learning_agent --locked python -m youtube_agent.evaluation --state 06_research_learning_agent/runtime/review-new --output 06_research_learning_agent/runtime/review.json
```

The runner covers research in both languages, multiple clips, quiz explanations,
flashcards, seven-day study plans and a one-step partial result. It uses real backend
jobs/validation and Chroma, with deterministic offline generation/embeddings. Its JSON
report retains each result, wall latency, provider metadata/usage and a manual review
checklist. A passing contract is not a passing semantic review: each checklist remains
`passed=null`, and `semantic_quality_verified=false`.

For real-video review, prepare a dataset matching `fixtures/acceptance.json` from authorized
03 transcript exports. Set `provenance` to `exported_transcripts`, preserve actual segment
IDs/timestamps, and update case scopes/topics/review criteria. Videos are explicit
`TranscriptResult` records, not raw unfiltered API response objects. The runner does not
fetch YouTube, overwrite an application database, or reuse a previous state directory.

With a configured account/model, adding `--dataset PATH --live` explicitly enables live
Gemini generation AND embeddings on those exports. This mode makes paid requests and
uses its own SQLite/Chroma pair; no live mode was invoked in this acceptance run.
Actual module-05 comparison/cancellation are additionally covered by integration tests,
which inject real `AnswerService` into the same RAG instance and mock only model responses.

Module 04's known runtime-versus-maintenance store/configuration mismatch is unchanged.
The 06 factory alignment and isolated runner do not repair 04's `reindex/gc` safeguards;
that remains a separate 04/02/05 coordination task.

## Limits and next integration work

- Direct artifacts currently enumerate evidence into one bounded generation input. Large
  corpora exceed the explicit context guard; no hidden truncation or complete-coverage claim
  occurs. Research preserves partial findings; direct artifact tasks report a classified
  error. Hierarchical artifact synthesis is a future extension.
- Local history/evidence uses a conservative UTF-8 byte guard. Live requests additionally
  call Gemini `countTokens` on native conversation contents, then reserve serialized config
  bytes plus framing for policy/tools/output schemas. The current Developer API SDK cannot
  count those config fields directly; this allowance is not an exact full-request token count.
- Live Gemini/account/model compatibility and real-video educational quality have not been
  evaluated by offline tests. Citation identity validation cannot establish semantic support;
  a real-content evaluation belongs with 05/07.
- No frontend, scheduler, live transcript adapter, account system or production deployment
  is implemented by this module.

Implementation references: [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling)
and [official Python SDK](https://github.com/googleapis/python-genai).
