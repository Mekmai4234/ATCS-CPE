# Module 05 follow-up acceptance — updated 2026-10-22

2026-10-24 Free Tier update: follow [VISUAL_HANDOFF.md](VISUAL_HANDOFF.md) first.
Earlier live commands below are historical prerequisites, not an authorization to use
paid APIs. 05 now requires the trusted shared broker even for text/catalog calls.
Without the upstream broker, live generation returns quota_pending before network.

Member authentication prerequisites and current dependency versions are documented in
[MEMBER_AUTHORIZATION.md](MEMBER_AUTHORIZATION.md). Earlier verification below remains
historical; the current authenticated test results are in [MEMBER_TEST_REPORT.md](MEMBER_TEST_REPORT.md).

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

**Dependency status:** this feature branch now includes `develop@6520b4c`, which merged
02 / PR #9, 04 / PR #10 and 03 / PR #14. The full launcher and store safeguards are
available in this checkout. The 02 full-flow test now checks resolved settings and hostile
dotenv inputs through supported interfaces instead of patching 05's removed `ENV_FILES`.
Pending 06/07 revisions are tested in an ignored isolated integration tree, without merging
their source changes into this branch; see `REVIEW_FIX_REPORT.md` for exact versions/results.

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
4. Sign in through the normal Google login flow. Load the resulting opaque server session
   cookie into the process environment variable `YK_ACCEPTANCE_SESSION` using your local
   secret handling workflow. The client accepts an existing session, not a Google ID token.
   Do not paste the cookie into command arguments, plans, reports or committed env files.
5. Run the opt-in acceptance client. It imports/reuses clips, polls import jobs until ready,
   asks QA/unsupported/follow-up cases, then requests summaries and conflicting comparison.
   Chat accepts both immediate 200 and asynchronous 202; follow-ups reuse conversation IDs.

```powershell
python -m uv run --project 05_ai_answers_analysis --extra team --locked yk-answers-acceptance --live --base-url http://127.0.0.1:8000 --origin http://localhost:3000 --plan runtime/answers05/real-plan.json --output runtime/answers05/real-report.json --request-timeout 210 --poll-timeout 300
```

The client calls `/api/auth/me` before importing and before each case, binds the run to
one active user and refreshes `X-CSRF-Token`. `--origin` must match a server-trusted
browser origin. HTTPS defaults to `__Host-yk_session`; local HTTP defaults to `yk_session`.
`--session-cookie` and `--session-env` select a cookie name/environment variable, never a
raw credential argument. Redirects are disabled. Missing/expired sessions, forbidden
access and actor changes fail explicitly; a fatal auth error discards earlier private
case results. Cookie values, CSRF tokens and auth response bodies are not exported.
Remove the process session variable after the run.

The client rejects fixture/offline/limited capabilities before import, checks status,
scope/coverage/model/provider, title, timestamp URL and transcript interval bounds. It
fetches paginated real transcripts and includes the overlapping segments for each citation.
Changed transcript versions/titles during the run fail acceptance. Wall latency and provider
usage/latency remain separate. A missing expected test category is recorded explicitly.
No semantic pass is ever assigned automatically.

HTTP read/write timeout defaults to 210 seconds, allowing the default 180-second backend
job budget plus 30 seconds for delivery. Connect timeout is capped at 10 seconds. These
are HTTPX per-operation limits, not a single wall-clock deadline for the whole acceptance
run. Polling has its own per-job budget (default 300 seconds). Increase both selected values
when using larger server/job budgets; invalid, zero, negative or infinite values are rejected
before any requests. Reports record the selected budgets and distinguish request timeout
from failed jobs. A timed-out HTTP request may leave a server job running: inspect jobs
before manually retrying rather than silently resubmitting a potentially paid request.

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
