# Windows HTTP test cleanup — 31 October 2026

Review: PR #42, 5721535137. Only test lifecycle changed; no production socket leak is claimed.

The loopback server now registers accepted writers/tasks synchronously, retains completed
handlers until teardown can observe exceptions, stops admission before cleanup, closes
accepted writers, and allows handler close/wait_closed to finish before cancelling only
remaining handlers. Teardown then awaits every writer and flushes connection_lost callbacks.
No ResourceWarning filter, skip, xfail or replacement of real HTTP with mocks was added.

Windows validation (Python 3.11, Proactor event loop):
- Full suite: 231 passed in 120.22 seconds, warnings treated as errors.
- Acceptance suite: 27 passed in 1.58 seconds.
- Timeout/success real HTTP pair repeated twice: 2 passed each run.
- Whole-module Ruff lint/format passed.
- pytest asyncio_default_fixture_loop_scope=function was supplied explicitly to avoid
  plugin configuration deprecation, not to suppress warnings or replace the loop policy.

CI Windows/Linux still needs the pushed source checked. No live provider requests.
Input/output moderation integration stays blocked on the reviewed 02 contract merging
into develop. See CHAT_REVIEW_HANDOFF.md; review signals remain unmounted.
