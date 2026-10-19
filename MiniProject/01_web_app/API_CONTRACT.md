# Frontend integration mapping

Reference: local Git `develop@25427fe`, `MiniProject/docs/backend_api_contract.md`
and `MiniProject/02_api_backend/src/youtube_backend/schemas.py`. This file records
the frontend's integration assumptions; it does not replace the backend contract.
The branch was subsequently synchronized with develop before the PR; backend files are inherited unchanged from develop.

| Operation           | Request                                                          | Response handling                                             |
| ------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------- |
| Library             | GET /api/videos?limit=50&offset=N                                | items[], total; explicit load more                            |
| Import              | POST /api/videos/import { urls[] }                               | 202; jobs[] mapped by input_index; accepted/existing/rejected |
| Observe             | GET /api/jobs/{job_id}                                           | state and stage are separate; terminal result lives in result |
| Chat                | POST /api/chat { question, conversation_id, scope }              | 200 final answer, or 202 job_id                               |
| Analysis            | POST /api/analysis { type, instruction, scope }                  | 202; summary/compare; compare needs >=2 filtered ready videos |
| Research            | POST /api/research { goal, level, days, scope }                  | 202 job_id/run_id                                             |
| Research events     | GET /api/research/{run_id}?after_event_id=N&limit=100            | events[] with monotonically increasing event_id               |
| Learning            | POST /api/learning-artifacts { type, topic, level, days, scope } | 202; read result.artifact_ids[]                               |
| Saved artifact      | GET /api/learning-artifacts/{id}                                 | typed content, citations, coverage, sources_available         |
| Cancel              | POST /api/jobs/{id}/cancel                                       | state/cancel_requested; continue polling until terminal       |
| Retry import/delete | POST /api/jobs/{id}/retry                                        | 202 replacement job_id for eligible failed retryable work     |
| Delete              | DELETE /api/videos/{video_id}                                    | 202 cleanup job; remove selected ID and refresh library       |

Scope: nonempty explicit video_ids (max 100), channel_ids, date_from/date_to.
No nonempty playlist filter is sent. The UI applies channel/date filters locally
to loaded library pages and carries the same constraints to task requests. Hidden
selected videos remain explicit selections; empty intersections are blocked rather
than widened. Dates are inclusive; unknown publication dates cannot match a range.
Backend remains authoritative and revalidates readiness and lifecycle versions.

Job states: queued, running, completed, partial, failed, cancelled. The last four
stop polling. Video stages: queued, fetching_transcript, indexing, ready,
no_transcript, failed, deleting, deleted. Completed import with no_transcript is
not a ready video. No progress percentage is fabricated.

Chat/analysis/research/artifact POSTs carry one UUID Idempotency-Key per logical
operation. A retry preserves the original JSON body, conversation/scope and key.
Once a job_id is known, observation resumes by GET instead of creating another task.
There is no automatic POST retry or automatic new key after uncertain delivery.
Import deduplication is by normalized video ID and does not use this header.

Errors: { error: { code, message, retryable, request_id, job_id? } }.
Observe X-Adapter-Mode and body mode to label fixture responses. In normal mode an
unavailable API remains an error. Demo transport is a build-time explicit opt-in.
Output text is escaped; citation links use validated IDs and floored source times.
sources_available=false disables all source links, including nested artifacts.

Server progress and final outputs are authoritative. Client polling has bounded
transient retries and can pause observation without relabelling the server job.
Streaming and session restoration are not implemented.
