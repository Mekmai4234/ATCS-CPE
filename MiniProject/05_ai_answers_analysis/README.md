# Module 05 — AI Answers and Analysis

Latest member authorization work: [MEMBER_AUTHORIZATION.md](MEMBER_AUTHORIZATION.md).
Member verification: [MEMBER_TEST_REPORT.md](MEMBER_TEST_REPORT.md).
Earlier review fixes and combined verification: [REVIEW_FIX_REPORT.md](REVIEW_FIX_REPORT.md).
Previous follow-up results: [FOLLOWUP_REPORT.md](FOLLOWUP_REPORT.md).
Live acceptance prerequisites and review workflow: [ACCEPTANCE.md](ACCEPTANCE.md).

`youtube_answers` generates cited answers, whole-video summaries and comparisons.
02 owns HTTP routes, durable jobs, history, retries and result storage. 04 owns versioned
evidence and embeddings. 05 supplies `answer(request, sources, history, context)` and
`analyze(request, sources, context)`, returning 02's existing `AnswerResult`.

This member integration changes only module 05. It depends on 02's authenticated
backend contract (PR #18); permission-aware 04/06 integration is tested separately.
The optional `youtube_answers.team:create_adapters`
composition connects existing 03 ingestion, 04 RAG, 05 answers and 06 research/artifacts,
with 06's comparison tool delegated to 05 and one shared RAG service.

## Install and test

From **MiniProject root**, Python 3.11–3.13 and uv:

```powershell
python -m uv sync --project 05_ai_answers_analysis --extra team --locked
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 05_ai_answers_analysis/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked ruff check 05_ai_answers_analysis
python -m uv run --project 05_ai_answers_analysis --extra team --locked ruff format --check 05_ai_answers_analysis
```

`team` installs 03 and 06 for integration tests and full composition. Without that extra,
05's service and `youtube_answers.integration:create_adapters` require only 02/04.
The latter factory enables index/delete/evidence/inventory/answer/analyze; ingestion,
research and learning artifacts remain unavailable through that smaller factory.

Offline tests use labelled synthetic transcripts and model/embedding doubles. Integration
tests exercise real FastAPI HTTP handling (ASGI in process), the actual worker, migrated
SQLite and persistent Chroma subprocesses. SDK tests use the real Google GenAI client
with HTTP mocks. No test requires credentials, downloads a model or calls a paid service.
This verifies mechanisms; it does not establish real-video answer quality.

## Configuration

Copy this module's `.env.example` to `.env` only if no local file already exists.
Credentials are server-only. Never commit `.env` or include keys in shell arguments.

The full-team factory consumes the backend's **resolved Settings**, with dotenv loading
disabled for all downstream services. Shared fields always use the supplied backend values;
module-specific fields missing from a legacy backend use process values/defaults only.
Use 02's **yk-full** launcher to select one file and export all service fields for API,
worker and reindex/GC: process environment > selected file > launcher defaults. Module-local
dotenv files must not silently select a different database, Chroma store or embedding model.
The narrow 05 factory follows the same resolved-backend rule; direct manual construction
of `AnswerSettings` is a separate standalone API, not the full runtime configuration contract.

| Setting | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | empty | Required only for live generation/embeddings |
| `LLM_MODEL` | `gemini-3.5-flash` | Configurable project-requested generation model |
| `LLM_TIMEOUT_SECONDS` | 60 | Per-operation ceiling, also limited by the job deadline |
| `MAX_CONTEXT_TOKENS` | 24000 | Application input budget, not provider capacity |
| `ANSWER_MAX_OUTPUT_TOKENS` | 1200 | Maximum output per model request |
| `RETRIEVAL_TOP_K` | 8 | Ranked question-answer retrieval |
| `ANSWER_READ_PAGE_SIZE` | 100 | Whole-video enumeration page size |
| `ANSWER_MAX_CHUNKS` | 5000 | Evidence memory/processing limit |
| `ANSWER_MAX_MODEL_CALLS` | 64 | Maximum generation requests per answer/analysis |
| `ANSWER_MAX_HISTORY_MESSAGES` | 12 | Maximum recent history entries |
| `ANSWER_MAX_HISTORY_BYTES` | 4000 | Serialized UTF-8 history budget |
| `ENABLE_STREAMING` | false | True rejected; only validated final results are supported |

Generation and embedding models remain independent. Verify actual Gemini model/account
access before using live mode; the configured identifier is not a claim of availability.
Requested and returned model/version, aggregate usage and provider-call latency are kept.

## Run the full team integration

The main runtime dependency set is **02_api_backend/full**, factory
`youtube_answers.team:create_adapters`. The older `02_api_backend/integration` set connects
only 04/06 and cannot supply 05 answers. `05 --extra team` remains the development/test
environment; it does not add 02's launcher when that backend version is absent.

This branch now includes `develop@6520b4c`, containing 02's full launcher (PR #9),
04's store safeguards (PR #10) and 03's follow-up changes (PR #14). The full-flow test
consumer was updated to validate resolved service values instead of the removed private
`ENV_FILES` constant. See [ACCEPTANCE.md](ACCEPTANCE.md) for maintenance commands.

Copy the example only if 05/.env does not exist, fill the key locally, and select a fresh
SQLite/Chroma pair. Every command must select the same file and process environment.
From MiniProject after the prerequisite is integrated:

```powershell
python -m uv sync --project 02_api_backend/full --locked
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env config
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env init
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env check
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env api
```

In terminal 2, select the same configuration:

```powershell
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env worker
```

Open [Swagger](http://127.0.0.1:8000/docs). Import a caption-accessible YouTube URL through
`POST /api/videos/import` and poll its job until `ready`. Then submit:

```json
{"question":"สรุปแนวคิดสำคัญจากคลิปนี้","scope":{"video_ids":["YOUR_VIDEO_ID"]}}
```

to `POST /api/chat`. For a whole-video summary use `POST /api/analysis`:

```json
{"type":"summary","instruction":"สรุปเป็นภาษาไทย","scope":{"video_ids":["YOUR_VIDEO_ID"]}}
```

For comparison use `type=compare` and at least two selected IDs. Poll `GET /api/jobs/{job_id}`
for asynchronous results. 02 handles conversation IDs, idempotency and saved messages.
06 research can call `compare_videos` through the same factory. Existing caption access
restrictions and 06's large-artifact context limits still apply. The root Docker Compose
image does not package this integration; the commands above use the local 05 environment.

## Behavior and guarantees

- Question answering adds bounded recent user history to retrieval for follow-up context,
  then generates only from retrieved evidence. This is a heuristic, not a semantic query
  rewriting guarantee. History is explicitly untrusted and cannot widen the frozen scope.
- Low-ranked evidence that does not fit the conservative input guard is omitted with a
  coverage note. If no usable item fits, the operation fails with `context_budget_exceeded`.
- Whole-video analysis enumerates every available selected chunk, summarizes bounded batches
  per video and recursively merges cited summaries. All available selected videos must be
  cited in an answered analysis. Missing indexes yield explicit partial coverage.
- Coverage measures distinct original chunks supplied to successful batch/answer generation,
  including batches reporting insufficient evidence. It does not prove every fact survived
  compression or was understood. Ranked QA always reports `complete=false`. Missing total
  inventory uses null chunk counts, as required by 02's schema.
- Each generated factual statement requires chunk IDs from its actual model input. Intermediate
  synthesis cannot cite an original chunk that was omitted from its supplied summaries.
  Final citation titles, exact intervals and timestamp URLs come from trusted source records.
  05 re-reads processed evidence before finalization; 02 revalidates before durable publication.
- A missing answer yields `insufficient_evidence`. Invalid JSON/citations, blocked/truncated
  output, source changes, budget exhaustion and timeouts produce classified failures, never
  a substitute factual answer. Partial coverage is in the AnswerResult; 02's analysis job
  state can still be `completed` because the operation returned a valid partial result.
- No SDK auto tools, no internal provider retries, no transcript-triggered external actions.
  SDK preflight+generation share one timeout. 02 owns durable transient retries and lease
  renewal. Cancellation/lease loss propagates and prevents final publication.
- Local budgeting reserves serialized UTF-8 bytes for evidence, policy and schema. Live
  requests also use Gemini countTokens on content plus a serialized-config byte allowance.
  This deliberately conservative allowance is not exact full-request token accounting.

## Evaluation and limits

`fixtures/evaluation.json` includes supported Thai, unsupported, conflicting cross-video,
follow-up and transcript-injection cases with manual review criteria. An optional live
smoke check makes paid generation requests on this small synthetic corpus only:

```powershell
python -m uv run --project 05_ai_answers_analysis --locked python 05_ai_answers_analysis/scripts/live_check.py --live --env-file 05_ai_answers_analysis/.env --output runtime/answers05/live-synthetic.json
```

It attempts an account-visible model catalog lookup, then checks expected status and citation
identity and saves outputs for semantic review. Catalog visibility does not prove generation
access; alias lookup failures are recorded separately from generation results.
It does not fetch YouTube, create embeddings or modify an application database. Inspect
each claim against the fixture, source attribution, contradictions, relevance and Thai
readability. Passing structural checks does not prove factual support or prompt-injection
resistance. Real-video grounding, model access, production throughput and live team behavior
still require separate evaluation. No live calls were made during offline verification.

For **real-video** import → ready → QA/summary/compare acceptance, use the new
`yk-answers-acceptance` client and `fixtures/real_acceptance.template.json` as described in
[ACCEPTANCE.md](ACCEPTANCE.md). It records wall latency, provider usage and a human review
packet pairing each cited paragraph with actual transcript segments and timestamps.
It refuses fixture/limited runtimes and never labels structural success as semantic acceptance.

The acceptance client defaults to a **210-second HTTP read/write timeout** (the default
180-second backend job budget plus a 30-second delivery margin), with a 10-second connect
timeout and a separate 300-second polling budget. Override `--request-timeout` and
`--poll-timeout` when the server has different budgets. All values must be finite and
positive. The report records these budgets. A request timeout does not mean the server
cancelled its job: inspect existing jobs before submitting another request.

Long analyses can exceed context, call-count or job-time limits and fail explicitly.
There are no resumable 05 checkpoints or guaranteed partial synthesis after a hard timeout.
There is no frontend, ASR, web search, scheduler, authentication or production deployment
provided by this module. See `TEST_REPORT.md` for executed checks and their limits.

References: [Gemini structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output),
[token counting](https://ai.google.dev/gemini-api/docs/tokens),
[Google GenAI Python SDK](https://googleapis.github.io/python-genai/).
