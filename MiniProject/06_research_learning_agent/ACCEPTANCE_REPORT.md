# Module 06 — Integration acceptance and hardening

Date: 2026-10-19 (Asia/Bangkok). Base checkout: `25427fe`.
All changes in this round are confined to `06_research_learning_agent`. Verification
was completed before publication for review.

## Changes made

1. The 06 adapter factory derives agent/RAG configuration from already-resolved backend
   Settings instead of rereading potentially conflicting module env files. Its async
   factory closes the generation client if composition setup fails. Standalone settings
   and the existing 05-owned team factory remain explicitly separate configuration paths.
2. Requests must include every frozen authorized source. Backend filters may legitimately
   narrow the original selection. Read/compare tool evidence must also stay inside that
   tool's narrower source subset, even if an injected knowledge adapter returns bad data.
3. Comparison observations now carry 05's numbered citation-to-chunk mapping and coverage.
   Duplicate reference labels are rejected. Tests use actual 05 AnswerService with the
   same actual 04 RagService instance as 06; only provider output is simulated.
4. Research, direct artifacts and partial results re-read exported citations and check
   vector inventory before returning. Changed/missing evidence and known index/source
   failures propagate as classified failures, rather than yielding a usable-looking partial.
5. Terminal run_controller progress events use the current step and actual final state.
   A proposed research finish is validating until source rechecks succeed. Direct artifacts
   emit collection and completion events. Cancellation inside actual 05 analysis is tested
   and prevents publication; backend job state remains the cancellation authority.
6. A new isolated evaluation runner accepts explicit transcript datasets and records outputs,
   measured wall latency, provider metadata/usage, contract checks and pending manual-review
   criteria. It refuses to reuse existing state directories. Live generation/embeddings
   require the explicit --live flag; no live mode was used in this round.
7. Added a Thai/English synthetic acceptance dataset, 22 additional tests, a development-only
   local dependency on 05, and updated the 06 Docker allowlist/image and operating docs.

No source/configuration/lockfile in 02, 03, 04, 05, 07 or the root was modified.

## Executed results

| Verification | Result |
|---|---|
| Windows suite, warnings treated as errors | **77 passed**, 22.35 seconds |
| Docker Linux suite, warnings treated as errors | **77 passed**, 26.54 seconds |
| Windows Ruff lint / format | Passed, 13 Python files |
| Docker Ruff lint / format | Passed, 13 Python files |
| Evaluation CLI, isolated synthetic dataset | **6/6 contract checks passed** |
| Git whitespace check | Passed |

Both full suites have zero failures, errors or skips. XML suite timings are 22.311 s and
26.534 s respectively; pytest reports include final overhead. The previous 55-test baseline
is retained in TEST_REPORT.md. These are test observations, not live application benchmarks.

New checks cover source changes during finalization, vanished citations, changed inventory,
known store errors, request/source mismatch, legitimate filtered scope, narrower tool scope,
ordered terminal events, direct artifact progress, shared backend settings and client cleanup.
Two additional integration scenarios verify actual 05 comparison/reference mapping and
cancellation within actual 05 generation. Evaluation checks cover report contents, existing
state protection, invalid dataset scope, duplicate IDs and unsupported request fields.

The actual backend API/worker/SQLite, source authorization, result validation, module 05
analysis orchestration and persistent Chroma are exercised. HTTP route tests are in-process
ASGI calls. Gemini SDK tests use actual SDK code with HTTP mocks. Transcript/model/embedding
fixtures remain explicitly synthetic. No live provider or YouTube calls were made.

Docker uses a non-root user, networking disabled, an empty Gemini key and temporary test
databases. The image copies 05 source as a test dependency without modifying it. Local
credentials, .env files, existing databases and indexes are excluded from the build context.
Test containers are removed after execution.

## Evaluation outcomes and quality boundary

The separate CLI run produced:

| Scenario | Actual state | Contract |
|---|---|---|
| Thai research | completed | Passed |
| English multi-video research | completed | Passed |
| Thai quiz with explanation | completed | Passed |
| English flashcards | completed | Passed |
| Seven-day study plan | completed | Passed |
| Research with a one-step budget | partial | Passed |

The saved report includes wall latency and provider usage for each operation. This run's
provider is fixture, so usage is synthetic/empty and timings are not Gemini performance.
Every quality checklist remains required with passed=null. semantic_quality_verified is
false: structural success does not establish correctness, relevance, useful topic order,
Thai fluency or resistance to prompt injection in real provider output.

Real-content review still requires authorized transcript exports and configured live
account/model access. Use the dataset's review criteria to inspect claims against source
passages, quiz answers/explanations, concise flashcards and study-plan order. The runner can
process exported_transcripts datasets in a NEW isolated store with --live when explicitly
requested. Real YouTube import and production frontend acceptance were not exercised here.

## Limits outside this delivery

The known 04 runtime/maintenance SQLite–Chroma configuration mismatch is NOT repaired.
06 now fails on the source/index errors it receives; this does not prevent an incorrectly
configured 04 maintenance command from changing that module's manifest. A proper store
identity guard and reindex/gc regression still belong to 04 with 02/05 coordination.

Large direct artifact inputs continue to fail explicitly at the context guard. Research
returns honest partial findings on context/step/time exhaustion, subject to final source
validation and the durable hard deadline. Hierarchical artifact synthesis and resumable
checkpoints are not added by this acceptance work.

## Reproduction and retained evidence

Commands and dataset instructions are in README.md. This round's ignored local outputs:

- runtime/acceptance-local-tests.xml
- runtime/acceptance-docker-tests.xml
- runtime/acceptance-evaluation.json
- runtime/acceptance-<unique-id>/ contains only this runner's isolated synthetic database/index.

Source, tests and documentation are ready for review; local runtime reports and datasets
remain excluded from version control.
