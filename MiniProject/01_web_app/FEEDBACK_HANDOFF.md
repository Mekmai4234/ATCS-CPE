# Feedback UI foundation — 31 October 2026

Draft module-01 component only; not enabled in production chat.

AnswerFeedback is controlled by server-confirmed state. It supports toggle/withdraw,
optional dislike reason/comment (500 characters), explicit save/retry, disabled pending
controls, 44px targets and accessible selected state. It renders untrusted comments as text.

02 dependencies: stable assistant message ID on 200/poll/history; authenticated feedback
read/write/delete with CSRF; capability-gated admin review APIs and audit; versioned input
confirmation. Endpoint names in the plan are proposals, not implemented API contracts.
The parent must key by member+message, fetch fresh state on session/history changes,
share updates across views and discard unmounted/session-stale requests. No localStorage,
client-side synthetic IDs, optimistic success or admin access bypass is provided.

Pending: wire full/floating/history, reload persistence, admin review and disclosure,
input guards and screenshots of integrated UI after 02 delivers the agreed contract.
This PR does not claim end-to-end feedback acceptance.
