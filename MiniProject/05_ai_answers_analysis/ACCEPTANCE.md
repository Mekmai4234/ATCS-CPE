# Module 05 follow-up acceptance — 2026-10-20

This checklist responds to the review of `develop@25427fe`. It separates code changes,
offline mechanism tests, live provider access and human semantic acceptance.

## Runtime and maintenance configuration

The primary full-system entrypoint is **02's `yk-full`**, using the locked environment
`02_api_backend/full`. It resolves one selected env file and exports all service fields
to API, worker, reindex and GC. The 05 factory now projects the supplied backend Settings
into answer/RAG/ingestion/Agent settings with `_env_file=None`; it never reopens module
dotenv files. Fields absent from legacy backend Settings use process/default values only.

Use one chosen file for every command. For example, from MiniProject:

```powershell
python -m uv sync --project 02_api_backend/full --locked
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env config
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env init
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env check
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env api
# A separate terminal, same file and process configuration:
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env worker
```

After stopping API/workers and finishing/cancelling queued jobs:

```powershell
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env reindex --workers-stopped --video-id YOUR_VIDEO_ID
python -m uv run --project 02_api_backend/full --locked yk-full --env-file 05_ai_answers_analysis/.env gc --workers-stopped
```

The launcher protects the SQLite/Chroma pair and fingerprint. New embedding/chunk settings
require a fresh pair/reimport under that contract; do not copy markers or adopt an old
fixture index. Direct `yk-rag`/`yk-api` commands do not select the common full env file.
The smaller `youtube_backend.team` factory connects only 04/06; it cannot perform 05 QA.
The required full factory remains `youtube_answers.team:create_adapters`.

**Dependency status:** the `yk-full` files are present on the local remote-tracking branch
`origin/feature/02_api_backend@ec3dff8`, not in this feature branch's checked-out 02 package.
04's independent maintenance/pair changes are on `origin/feature/04_rag_knowledge@ae2ab1a`.
Neither branch was merged, copied into other modules, committed or published in this work.
The commands above require the team to integrate 02's full launcher first. This is an
explicit prerequisite, not a claim that those commands already exist on this checkout.

Offline tests verify shared backend values, hostile process/dotenv values, and identical
runtime/maintenance storage/fingerprints after a full environment export. The 05 tests use
the installed 02–06 contracts; cross-branch acceptance is recorded separately if performed.

## Gemini model and account access

The configured project identifier stays `gemini-3.5-flash`. As checked against Google's
documentation on 2026-10-20, this identifier is deprecated and routes to `gemini-3.6-flash`:
[model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash.md),
[routing note](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5).
Keep requested and returned models distinct. Documentation does not establish this
account's permissions, quota or successful generation. No account check can be completed
without a configured key.

The existing synthetic smoke script now accepts one explicit env file and first attempts
a bounded model catalog lookup. A failed alias lookup is recorded; generation results
remain the evidence of actual access. The script never treats catalog visibility alone
as successful generation. To opt in deliberately:

```powershell
python -m uv run --project 05_ai_answers_analysis --locked python 05_ai_answers_analysis/scripts/live_check.py --live --env-file 05_ai_answers_analysis/.env --output runtime/answers05/live-synthetic.json
```

This is still **synthetic generation**, not acceptance against real videos.

## Real-video HTTP acceptance and review packets

1. Choose two actual caption-accessible clips, including genuinely conflicting content and
   at least one long clip. Configure credentials locally, never in the plan or chat.
2. Copy `fixtures/real_acceptance.template.json` to an ignored runtime path. Replace every
   placeholder video ID/question and specify the model the server requests. The template
   intentionally fails validation before making requests until completed.
3. Start the real full API and worker with the selected common configuration above.
4. Run the opt-in acceptance client. It imports/reuses clips, polls import jobs until ready,
   asks QA/unsupported/follow-up cases, then requests summaries and conflicting comparison.
   Chat accepts both immediate 200 and asynchronous 202; follow-ups reuse conversation IDs.

```powershell
python -m uv run --project 05_ai_answers_analysis --extra team --locked yk-answers-acceptance --live --base-url http://127.0.0.1:8000 --plan runtime/answers05/real-plan.json --output runtime/answers05/real-report.json
```

The client rejects fixture/offline/limited capabilities before import, checks status,
scope/coverage/model/provider, title, timestamp URL and transcript interval bounds. It
fetches paginated real transcripts and includes the overlapping segments for each citation.
Changed transcript versions/titles during the run fail acceptance. Wall latency and provider
usage/latency remain separate. A missing expected test category is recorded explicitly.
No semantic pass is ever assigned automatically.

Each paragraph containing citations becomes a **claim candidate** with its source excerpts
and `pending_human_review`. Split paragraphs containing several factual claims during review.
Play every cited interval and compare each claim against the source text and context:

- Is the claim actually supported, or merely related to the cited topic?
- Are speaker, title, timestamps, date/version, qualifications and contradictions preserved?
- Does an unsupported question refuse rather than infer an answer from general knowledge?
- Does a follow-up resolve the intended reference without treating prior answers as evidence?
- Does a long/multi-video summary omit important points despite complete processing counts?
- Does a partial result explain exactly what was unavailable? `complete` measures processing,
  not semantic correctness; a backend analysis job may be completed with partial coverage.

For each claim record supported/partially_supported/unsupported, reviewer notes, and the
observed source interval. Record separate case-level readability, relevance and coverage
decisions. Approve acceptance only after all required cases and every claim are reviewed.
The report's initial semantic status deliberately stays pending, even when structural checks pass.

## Handoff points

- 01: render status, citation labels, coverage notes and partial limitations; do not infer
  complete knowledge from a completed job or display a retrieval score as confidence.
- 02: integrate `yk-full` and its full locked dependency set; keep selected-file and process
  values identical for API/worker/maintenance and preserve 200/202 polling behavior.
- 04: verify fingerprint/pair diagnostics with the same exported configuration; maintain
  versioned scoped evidence and explicit source-change errors.
- 06: comparison still calls `analyze(request, sources, context)` and preserves provenance.
- 07: use the real plan/report and human claim decisions, separated from synthetic SDK tests.

These are reviewable integration notes; no messages were sent to other team members.
Live acceptance remains pending until credentials, actual clips and human source review
are available. Offline tests and a prepared client do not satisfy that criterion by themselves.
