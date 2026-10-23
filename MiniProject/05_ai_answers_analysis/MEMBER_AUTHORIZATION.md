# Module 05 member authorization — 2026-10-22

This change addresses the five supplied member-phase review documents. Deliverables
are confined to module 05. The branch is stacked on 02's auth PR #18 at
`b047e809f983ffb2e4f3f9d3e3f074b8976cd6da`, based on `develop@69f5347`.
Its PR targets the auth branch so the diff contains only 05; retarget to develop after
the prerequisite is merged. Earlier reports describe earlier phases.

## Trusted execution

For authenticated runtime settings, generation requires the real backend execution
context and its `authorize_sources` contract. MemberContext checks the durable job
owner/kind, active account, current library grants and conversation owner. It snapshots
account update time and grant creation identities alongside source generation/version.
The same wrapper reaches 04 and is checked before/after external awaits and before
returning results. A removed/replaced grant or changed account invalidates the run;
provider output is discarded. Backend cancellation, lease and deadline errors propagate.
02 still owns atomic final publication and rechecks durable permissions there.

Sources are copied from the authorized frozen job. Server-resolved filters may narrow
the requested videos, but may never introduce another video. Chat history must match
the frozen job payload, and a supplied conversation ID must match that job. User IDs
are never derived from request extras, prompts, history, model output or worker globals.
06 may call the analyzer within its owned research job. No answer/history cache or
independent identity store is introduced. Future caches must include owner, grant
identity and source snapshot, with authorization rechecked on access.

Admin status grants no private history/content bypass. HTTP polling, retry, cancel,
idempotency and conversation reads remain 02's owner-scoped responsibilities. Session
expiry controls HTTP access; a durable worker uses its job owner and current account/
library permissions rather than retaining a browser session.

## History and source lifecycle

Detaching a video preserves private conversation history but makes citations unavailable
according to 02's current library/generation/version checks. A delete and reimport that
creates a new generation must not revive old citations. Reattaching an unchanged central
source can become available again only if 02's membership and version checks pass;
05 does not override that backend policy. Historical text is context, never new evidence.

## Session acceptance and configuration

Use normal Google login to obtain an opaque server session, then load it locally into
`YK_ACCEPTANCE_SESSION`. See [ACCEPTANCE.md](ACCEPTANCE.md) for the command. The CLI
requires an active `/api/auth/me` response, refreshes CSRF and binds the run to one actor.
It supports shared-source attach receipts and the existing 200/202 job behavior.
Missing session/401/403/actor change fail separately from insufficient evidence. Secret
values and auth response bodies are excluded from reports, including fatal-error reports.

Keep `AUTH_ENABLED=true`. Configure `GOOGLE_CLIENT_ID` and trusted origins in the common
02 launcher configuration. `.env.example` uses insecure cookies only for local HTTP
development; production requires HTTPS/secure cookies. Offline integration tests use
real challenge, sessions, CSRF, migrations, workers and permissions with a synthetic
Google verifier, transcript source and model. No live login or paid provider is called.

## Dependencies and limits

The isolated member candidate uses 03 PR #19 (`4b05131`), permission-aware 04 PR #20
(`d4aa52d`), 06 PR #21 (`84fb1b6`) and 07 PR #22 (`04c8352`) on auth PR #18.
Those modules are copied only into an ignored test tree; their changes are not part of
this PR. See [MEMBER_TEST_REPORT.md](MEMBER_TEST_REPORT.md) for executed checks.
05's lock metadata includes auth backend dependencies and must pass `uv lock --check`
against the selected sibling contracts. This work does not resolve other modules'
review findings or establish production/live semantic acceptance.
