# Video Buddy: chat navigation and history

Updated 26 October 2026. Modules 01 and 02.

- Brand text on login, shared logo, public information, member pages, footer and document title is Video Buddy. Existing mascot artwork is retained. The internal launcher storage key and asset paths remain compatible; source-content references to RAG are still the subject being discussed.
- Navigation separates Home, My Videos, Chat with Buddy, Summaries and Exercises, and Chat History. Public help explains the actual launcher controls and saved history.
- Full-page submission collapses the source picker and reveals the pending response. Completion reveals the latest turn. Wheel/touch/keyboard upward reading opts out of automatic follow; an independently positioned latest-answer button restores it. The floating chat scrolls inside its own panel.
- `/history` loads `GET /api/conversations?q=...&limit=20&offset=...`. Titles use the first question (up to 160 characters), updated time, message count and source IDs from the latest saved scope. No model call is made for titles, search or reads.
- `/chat/{conversation_id}` loads every page of the existing authorized history endpoint. The additive `scope` field restores the last saved request filters. Old responses without it fall back to the actual saved source IDs.
- Reading never submits a chat request. Explicit continuation enables the composer and reuses the saved conversation when the source/filter fingerprint matches. Changing scope starts a new conversation. New chat clears the visible thread and uses `/chat` without deleting server history.
- User-only messages from failed/pending jobs show their state rather than a fabricated answer. Missing/foreign history is rejected and can be retried explicitly. History requests are aborted on navigation/session cleanup and personal history is never stored in browser storage.

## Validation

New browser cases cover history search/pagination, reload, explicit continuation with identical scope, foreign-history denial, branding, answer visibility and preserving an older answer while a new one arrives. Existing source-lifecycle tests now expand the source picker before interacting with it.

Module 02 passed 135 offline tests, including owner isolation over shared videos, literal wildcard search, pagination limits, pending-question retention and the existing chat contract. Frontend unit tests, production build/login gate and formatting were checked separately. Real HTTP identity acceptance uses isolated backend state and external provider fixtures; it does not certify live Gemini access.

Live localhost inspection found 19 pre-existing conversations and opened a saved answer with timestamp citations. No new real-provider chat, credential change, schema migration or historical-data rewrite was required by this feature.
