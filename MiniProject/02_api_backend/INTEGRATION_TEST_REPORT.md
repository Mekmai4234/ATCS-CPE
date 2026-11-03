# Module 02 integration verification — 2026-10-18

Scope: connect the existing 04/06 packages through 02-owned configuration, lifecycle,
capabilities, packaging and Docker. All delivered changes are inside `02_api_backend`.
The source/manifests/locks of 04/06, root configuration and existing application data
were not changed. Verification was completed before commit and PR publication.

## Final-source results

| Check | Observed result |
|---|---|
| Windows combined 02 + integration suite, warnings as errors | **77 passed**, 58.51 seconds |
| Linux Docker combined suite, warnings as errors, networking disabled | **77 passed**, 70.01 seconds |
| Existing 04 regression suite in the combined environment, live opt-in disabled | **77 passed, 1 skipped**, 91.00 seconds |
| Existing 06 regression suite in the combined environment, warnings as errors | **55 passed**, 23.70 seconds |
| Lightweight 02 environment without optional youtube_rag/youtube_agent packages | **68 passed**, 15.87 seconds |
| Ruff lint / formatting | Passed |
| Explicit schema init and offline-only transcript seed in non-root containers | Passed |
| Separate API/worker HTTP workflow with actual persistent Chroma and 06 controller | Passed |
| Container recreation with SQLite/index/jobs/artifacts retained | Passed |
| Real vector deletion and historical source availability | Passed |

The single skipped 04 check is its deliberately disabled live-provider test. No paid
Gemini or YouTube calls were made. Test wall times are observations, not production
application latency measurements. Windows uses Python 3.11.16; pinned Docker images use
Python 3.11.17 and UID 10001. Docker Engine 29.8.0/Compose 5.5.1 were used. Dependencies
are pinned in the separate `integration/uv.lock`, including ChromaDB 1.5.9 and GenAI 2.31.0.

## Added / changed behavior

- Lazy adapter construction after schema/profile checks, shared concurrent startup, and
  async closure on lifespan exit, worker cancellation/SIGTERM or partial startup failure.
  Model/RAG resources close before DB disposal. Legacy injected adapters remain compatible.
- Backend-owned `youtube_backend.team:create_adapters` composition reuses 04's RAG service
  for exact evidence/index operations and 06's real research/artifact controller.
- One backend-resolved configuration supplies both modules, including agent steps/time,
  finalization reserve, key/model, embedding configuration and persistent paths. The optional
  02 integration override file takes precedence over the old shared embedding proposal.
- Explicit offline profile uses labelled transcript/model/embedding doubles with real
  SQLite/Chroma. Live profile requires a configured key and Gemini embedding settings;
  it has no fallback to synthetic results. Jobs persist the custom factory/profile identity.
- Health exposes capability states and synthetic-data/profile flags without a paid probe.
  Missing 03/05 operations return a structured non-retryable 503 before enqueue.
- Dedicated combined lock/environment and digest-pinned runtime/test Docker targets.
  Root Compose/build configuration and other modules were not edited.
- A real timeout-boundary failure found during testing was fixed: a hard total timeout
  cannot be automatically requeued merely because the asyncio timer fires just before
  the recorded wall-clock deadline. A shorter chat-attempt timeout still retries within
  its total budget. Both cases have dedicated regression tests.

## Integration exercises

- Explicit 02 migration then additive 04 manifest initialization on a new DB.
- Guarded CLI seeding of labelled transcripts through actual lease/version/index/ready logic.
- API capability reporting, rejection of live-import/chat/analysis while 03/05 are absent.
- Three artifact types with item citations and actual evidence/version/time validation.
- Research reads real Chroma chunks, chooses subsequent tools through 06, records events,
  creates artifacts, and persists complete or honest partial results.
- Idempotent task replay, source-scope boundaries and blocked offline-to-live relabelling.
- Running cancellation/source deletion prevents final publication.
- Close during startup, startup failure cleanup, worker cancellation and repeated shutdown.
- Fresh DB engines/adapters reopen saved data; Docker force-recreates BOTH API and worker,
  then processes a pending job against the same named SQLite/Chroma volume.
- Deleting one source removes actual vectors/transcripts, marks stored artifacts unavailable,
  and leaves the other source usable for a subsequent artifact request.

## Reproduction and retained evidence

From MiniProject:

```powershell
uv sync --project 02_api_backend/integration --locked
uv run --project 02_api_backend/integration --locked pytest 02_api_backend/tests 02_api_backend/integration/tests -q -W error
uv run --project 02_api_backend --locked python 02_api_backend/scripts/docker_integration_smoke.py --keep
```

The final successful Docker project is `yk02-check-74caae94f0`. Its API/worker and
isolated named volume were intentionally retained for inspection. Swagger is at
`http://127.0.0.1:56627/docs`. The deletion check removed the first sample; the second
sample `jNQXAC9IVRw` remains ready with a labelled synthetic transcript.

Ignored local evidence:

- `runtime/yk02-check-74caae94f0/report.json`
- `runtime/yk02-check-74caae94f0/docker.log`

Full install/schema/start/stop guidance, profile isolation and live setup are in
[integration/README.md](integration/README.md). Live-generation compatibility, real-video
quality, multi-user access control, production load and operational restore drills were
not verified. Module 03 ingestion and 05 answer/analysis remain external integration work.
