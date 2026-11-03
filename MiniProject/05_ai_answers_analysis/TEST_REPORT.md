# Module 05 verification report

Executed on 2026-10-19 (Asia/Bangkok), Windows, Python 3.11.9. All source changes are
within `MiniProject/05_ai_answers_analysis`. Existing modules' source, tests, manifests
and lockfiles were not changed. A local ignored 05/.venv was created for verification.

## Results

| Suite/check | Observed result |
|---|---|
| 05 service, SDK and integration tests | **66 passed** in 45.40s |
| Existing 02 backend tests | **68 passed** in 17.25s |
| Existing 03 ingestion tests | **69 passed** in 18.39s |
| Existing 04 RAG tests | **77 passed, 1 skipped** in 79.93s |
| Existing 06 Agent tests | **55 passed** in 32.59s |
| Ruff lint on all 05 Python files | Passed |
| Ruff format check on all 05 Python files | Passed (14 files) |
| `git diff --check` | Passed; Git printed normal local LF/CRLF conversion notices |
| Source distribution and wheel build | Passed |
| Optional live-check CLI help | Passed; no generation requests made |

Total across separately executed suites: **335 passed, 1 skipped**. Every pytest command
used `-W error`. The skipped 04 test explicitly requires `RUN_LIVE_EMBEDDING_TESTS=1`
before live Gemini embeddings are allowed; it was not enabled.

## What was exercised

- Grounded answers, no retrieval hits, model-declared insufficient evidence, recent-history
  limits and follow-up retrieval context without widening scope.
- Unknown/out-of-scope citation IDs, wrong transcript versions, mismatched request scope,
  duplicate IDs, uncited structured statements and changed evidence before finalization.
- Correct citation labels, trusted video titles/intervals/URLs, measured ranked coverage,
  provider metadata and aggregate usage.
- Full paginated analysis, per-video batching, long Thai evidence, recursive synthesis,
  retained video provenance, missing-index partial results and required per-video citations.
- Explicit chunk/call/context limits, oversized evidence, nonadvancing pagination and
  synthesis attempts to cite chunks absent from an intermediate model input.
- Async deadlines, cancellation, lease loss, source deletion and prevention of final publication.
- Real Google GenAI SDK HTTP serialization: countTokens preflight, JSON schema, separate
  trusted system policy, no tools, bounded output, model metadata and classified/redacted
  400/401/403/408/429/500/503/transport/timeout failures without internal retries.
- Invalid JSON, blocked/truncated/no-candidate output and unexpected function calls.
- Actual 02 FastAPI HTTP handling via ASGI, durable worker, schema migrations, SQLite result
  and conversation persistence, idempotency and database reopen.
- Actual 04 persistent Chroma subprocesses with deterministic fixture embeddings.
- 06 research calling real 05 comparison and consuming its validated source evidence.
- Optional full-team factory construction/shared RAG/analyzer binding with synthetic keys,
  no provider requests, rejection of the offline profile and idempotent shutdown.

The synthetic fixture/model doubles are explicitly labelled. The SDK tests use MockTransport;
they validate SDK wire compatibility and application behavior, not a live Google response.

## Reproduce

From MiniProject root:

```powershell
python -m uv sync --project 05_ai_answers_analysis --extra team --locked
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 05_ai_answers_analysis/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked ruff check 05_ai_answers_analysis
python -m uv run --project 05_ai_answers_analysis --extra team --locked ruff format --check 05_ai_answers_analysis
python -m uv build --project 05_ai_answers_analysis --out-dir 05_ai_answers_analysis/runtime/dist
```

The four regression suites were run separately using the same 05 locked environment:

```powershell
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 02_api_backend/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 03_video_ingestion/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 04_rag_knowledge/tests -q -W error
python -m uv run --project 05_ai_answers_analysis --extra team --locked pytest 06_research_learning_agent/tests -q -W error
```

Selected locked versions: google-genai 2.31.0, ChromaDB 1.5.9, Pydantic 2.14.1,
httpx 0.28.1, pytest 9.1.1. The complete dependency set is in `uv.lock`.

Build artifacts are in the ignored `05_ai_answers_analysis/runtime/dist/` directory.
No real credentials, existing application database or production index were used.

## Remaining verification limits

No live Gemini/YouTube/embedding requests, model/account-access checks, real-video semantic
evaluation, external HTTP server deployment, Docker run, production load test or operational
restore drill were performed. The optional live-check script was not run with `--live`.
Citation identity/scope validation and processing coverage cannot prove semantic support,
complete retention during summarization or general prompt-injection resistance.

`fixtures/evaluation.json` and `scripts/live_check.py` provide a small opt-in synthetic
generation review workflow. Review actual claims, attribution, contradictions and Thai
readability manually before evaluating on authorized real-video transcripts. See README.md
for configuration, startup instructions, scope and budget limitations.
