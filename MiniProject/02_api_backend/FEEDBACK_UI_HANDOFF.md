# Current UI handoff — 31 October 2026

`CHAT_REVIEW_CONTRACT.md` describes implemented APIs in develop, not proposed paths.
The older module-01 handoff still describes components without mounted integration;
01 owns updating that file and wiring its full/floating/history/admin views.

| UI input/state | Authoritative contract |
| --- | --- |
| Saved assistant ID | chat 200/job result `assistant_message_id`; history `message_id` |
| Rating read/write/withdraw | GET/PUT/DELETE `/api/messages/{message_id}/feedback` |
| Response | `{message_id, feedback}`; feedback null after withdrawal; revision/update epoch supplied |
| Like/dislike | `rating=like|dislike`; like has no reason/comment |
| Dislike reasons | `off_topic`, `incorrect`, `citation_mismatch`, `insufficient_evidence`, `inappropriate`, `other` |
| Optional detail | reason optional, comment max 500 characters; explicit later PUT saves edits |
| Current saved state | server feedback in GET, successful chat, poll result and history; share by member+message |
| Input check | POST `/api/chat/check` with exact ChatRequest; allow/warn/block |
| Warning confirmation | `moderation_token`, exact question/scope/conversation, 300-second ticket |
| New expired/changed confirmation | 422 `moderation_confirmation_required`; request a new ticket |
| Blocked input | 422 `moderation_blocked`; no new job/provider work |
| Existing transport replay | identical owned key/hash returns existing job even with expired/missing token |
| Changed payload under old key | 409 `idempotency_conflict`; never silently replace original work |
| Resume | POST `/api/jobs/{job_id}/resume`, optional token; existing replacement lookup is read-only |
| Suppressed output | `visibility=withheld`, neutral system answer, no draft/citations/feedback |
| Ordinary insufficiency | status `insufficient_evidence`, visibility published; not an out-of-scope verdict |
| Policy/notice | GET `/api/chat/policy`; local policy `chat-local-v1` |
| Admin content | dedicated `/api/admin/chat-reviews` and `/api/admin/chat-messages` routes |
| Expired moderation case | 404 on detail/PATCH; absent from lists/counts even before purge |

401 means reauthenticate/clear account state; 403 means CSRF/Origin or missing admin
capability; 404 includes foreign resources and expired cases; 409 includes conflict,
busy conversation and non-rateable placeholders. Other retryable task/quota codes
retain the existing job/pause contract. Do not convert every failure to optimistic
success. Read errors through the standard `{error:{code,message,retryable,request_id}}`.

All mutations use the real session cookie, trusted Origin and X-CSRF-Token. Render
comments/questions/notes as text. Drop stale responses after logout/account/message
changes, obtain fresh server state after reload and preserve prior confirmed state
when saving fails. Never rate pending/user/system-placeholder messages. Do not
enable review content until the notice and real UI integration pass acceptance.
