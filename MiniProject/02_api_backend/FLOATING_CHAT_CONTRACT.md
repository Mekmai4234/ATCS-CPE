# Floating and full-page chat integration — 2026-10-24

Both surfaces use the existing authenticated `/api/chat`, job and conversation
routes. There is no widget-specific session, database, websocket or pointer API.
The backend does not distinguish the two surfaces: use the same cookie session,
in-memory CSRF token and selected conversation ID in their shared frontend state.

[Complete JSON examples](tests/fixtures/floating_chat.examples.json) were captured
from these HTTP routes using explicitly synthetic Google/provider adapters. They
include auth, chat 200/202, queued job, paginated history and error bodies and are
validated against the current Pydantic/OpenAPI schemas by `test_chat_contract.py`.
IDs are illustrative; replace them with IDs returned by the current session.
The example nonce/CSRF/credential values are placeholders, never usable credentials.

## Authenticate once, share the session

| Request | Response / action |
|---|---|
| `GET /api/auth/challenge` | 200 `{client_id, nonce, csrf_token}` plus HttpOnly challenge cookie. Initialize the Google JS callback flow with this exact client ID/nonce. |
| `POST /api/auth/google` | JSON `{credential, csrf_token}` using the challenge CSRF, credentials and trusted browser Origin. 200 `{user, csrf_token}` plus HttpOnly session cookie. |
| `GET /api/auth/me` | 200 `{user, csrf_token}` restores the session; 401 means clear private state. |
| `POST /api/auth/logout` | Session cookie, Origin and session `X-CSRF-Token`; 200 `{logged_out: true}` revokes the session. Clear private UI immediately, including if the network response is uncertain. |

Use `credentials: "include"` for cross-origin fetch and `X-CSRF-Token` on POST/DELETE.
Session CSRF differs from login challenge CSRF. Keep it in memory; never store
Google credentials, cookie values or chat history in localStorage. Discard the
Google credential after exchange. Only server verification determines the Google
subject; repeated subject logs into the same account, new subjects start as user.
There is no browser-supplied role or email/password registration path. Admin
bootstrap remains the operator command in AUTH.md.

Prefer a same-origin `/api` proxy. An explicitly configured cross-origin frontend
must also be same-site for SameSite=Lax cookies; cross-site cookie deployment is
not supported. Use a consistent localhost/127.0.0.1 host. Secure production cookies
require HTTPS. No environment names or authentication modes are added in this PR.

Module 02 now wraps authentication middleware with its existing exact-origin CORS
policy. Allowed credentialed frontends can read 401/403 bodies and `X-Request-ID`
even when authentication rejects a request before routing. Unknown origins remain
unapproved. API successes and errors use `Cache-Control: no-store`.

## Send a scoped turn and handle 200 / 202

Select at least one ready library video; `scope.video_ids=[]` is invalid (422).
`GET /api/videos` lists only the current account's library. Do not auto-select all
global clips or call unscoped/general chat when the library is empty.

```javascript
const body = {
  question: "Explain RAG from these clips",
  scope: { video_ids: selectedReadyVideoIds },
  ...(conversationId ? { conversation_id: conversationId } : {}),
};
const response = await fetch(`${apiBase}/api/chat`, {
  method: "POST", credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRF-Token": sessionCsrf,
    "Idempotency-Key": turnKey,
  },
  body: JSON.stringify(body),
});
```

Handle the HTTP status before treating the JSON as an answer:

- **200:** `ChatResponse` contains `job_id`, `conversation_id`, `status`, `answer`,
  `citations`, `coverage`, `provider_metadata`, `mode`, `sources_available`.
  `status` is `answered` **or** `insufficient_evidence`; the latter is not an
  evidence-backed answer and can have no citations. There is no streaming payload.
- **202:** `{job_id, state}` and `Location: /api/jobs/{job_id}`. This is a pending
  turn, not an answer. Poll that path. Chat can return 202 when a different worker
  owns the lease or a retry is queued; a long request is not guaranteed to return
  202 merely because the frontend has a thinking animation.
- **Polling:** `JobResponse` includes `conversation_id`, `state`, `stage`,
  `error_code`, `retryable`, `result`, `sources_available`. On `completed`, chat
  `result` holds the answer/IDs; the current source-availability flag is on the
  **outer job response**, so preserve it when rendering `result`. Treat
  failed/cancelled as failures, not ordinary no-evidence results. Polling a chat
  job does not use the research events endpoint.

Create one stable turn key before sending (1–128 characters matching `\w`, `.`,
`-`). Reuse the exact key and body after duplicate clicks/network uncertainty.
Changing input with the same key returns `409 idempotency_conflict`. A key is scoped
to account and operation, but the widget and full page must share the same pending
turn/key; two independent keys legitimately create two turns. No key means there
is no request deduplication guarantee. Import does not support this header as a
deduplication contract. No automatic Google exchange/mutation retries are proposed.

`POST /api/jobs/{job_id}/cancel` returns the owned job. Explicit manual
`POST /api/jobs/{job_id}/retry` returns 202 with the eligible new/active job ID;
follow that ID. A completed turn is not a retryable failed task. Neither operation
accepts a browser owner ID. Do not resubmit chat as a retry of an already known job.

## Conversation and source lifecycle

Omit `conversation_id` for a new conversation. For 200, save the returned ID; for
202, obtain it from job polling. Continue with that ID from either surface.
Only one queued/running turn may exist in a conversation; an additional turn
returns `409 conversation_busy`. Closing/minimizing the widget does not create a
new conversation, cancel a job or erase server history. There is no conversation
list/create/delete API in this contract; do not invent one for the widget.

History is `GET /api/conversations/{id}?limit=50&offset=0` (limit 1–200, offset >=0).
It returns `{conversation_id, messages, total, limit, offset}` in chronological
order. Each message includes `message_id`, `job_id`, `role`, `content`, frozen
`scope`, `state`, timestamp and `citations`. Use `message_id` to reconcile pages;
reload/reconcile after the pending job finishes. A pending/failed user message may
already be present; it is not evidence that an assistant answer succeeded.

Scope is frozen per **job/turn**, not per conversation. Continuing an owned
conversation with a different authorized scope is supported, but only completed
history whose entire frozen source set/version fits the new scope is sent to the
provider. Prior displayed messages remain historical messages with their original
scope. Recommended UI policy: explicitly start a new conversation when the source
selection changes; retain an existing ID only if the UI deliberately shows mixed
historical scopes. Starting over means omit the ID, not delete server history.

Historical owner-visible text/citations are retained after detach; availability
does not grant new retrieval access. `sources_available=false` marks a stored
answer/job unusable as current evidence. History citations have individual
`source_available` flags. Disable stale citation actions and offer re-selection;
never render old citations as evidence retrieved by a new request. Idempotent
replay can return the same old answer with current availability false. New chat
against removed/foreign sources is rejected even with the old conversation ID.
An explicit shared import grants only source membership, never another account's
jobs, results or conversation. Admin is not a private-content bypass.

Citation `url` is server-validated to the source video and timestamp; do not build
an arbitrary URL from model text. The backend checks evidence identity/source
version and timestamp bounds before storing a successful answer. There is no
public citation lookup endpoint granting access by a guessed chunk/citation ID.

## Distinct states and errors for 01/05

Errors have `{error: {code, message, retryable, request_id, job_id?}}`.

| HTTP / code or result | UI meaning |
|---|---|
| Empty library / no chosen clips | Show a selection/import action; do not send chat. |
| 422 `validation_error` | Invalid/empty scope or body; correct the input. |
| 409 `video_not_ready` | Import/index not ready; inspect video/import job state. |
| Import `no_transcript` / failed job | No captions/import failure; do not offer that video as ready. |
| 422 `empty_scope` | No ready selected videos match channel/date filters. |
| 404 `video_not_found` | Removed, unknown or foreign source; do not reveal which. |
| 200 `status=insufficient_evidence` | An authorized completed attempt found insufficient evidence. |
| 409 `conversation_busy` / `idempotency_conflict` | Wait for pending turn / preserve or replace the turn key appropriately. |
| Job `source_changed` / `cancelled` | Stop current result rendering; select valid current scope before a new turn. |
| 401 `authentication_required` | Anonymous/expired/revoked session or inactive account: abort polling and clear private state. |
| 403 `csrf_invalid` | Missing/stale CSRF or wrong Origin; refresh/restore safely, do not retry the mutation silently. |
| Login 403 `account_suspended` | Show account-access rejection; never fall back to demo data. |
| 502/503/504 or failed job | Provider/dependency/timeout error; inspect error/job retry eligibility. |

On logout, account change or 401, clear conversation IDs, source selection, message
cache, CSRF and turn keys together in 01. Abort requests and bump a frontend session
revision; ignore any old response completing after that revision changes. A response
already sent before logout cannot be recalled by the backend. 02 rejects subsequent
old-cookie requests; 01 owns this stale-response rendering guard. Synthetic demo
mode must remain explicit and must never be a fallback for an authentication failure.

02's request logger records only request ID, method, status and latency. It does not
log Google credential, session/CSRF values, query strings or full message bodies.
Ingress/access logging and frontend telemetry must follow equivalent redaction.

## Verification boundary

See FLOATING_CHAT_TEST_REPORT.md for observed tests and exact refs. HTTP/session/
ownership checks use actual backend routes with named external test doubles. Full
integration uses real 03 normalization, 04 persistence and 05 answer service; model
and embedding transport remain synthetic. Browser checks of pending 01 likewise
do not prove real Google login or live Gemini quality. No production credentials,
existing stores or real account data are needed for these contract checks.
