# Phase 2: web acceptance procedure

Status: procedure only. Live acceptance stays pending until the selected release
candidate has corresponding real-system evidence.

## Offline checks

From `MiniProject/01_web_app`, install the locked frontend dependencies and run:

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm test:browser
```

For the opt-in HTTP/session/worker/history/feedback integration suite, run from
`MiniProject` using the shared full-backend environment:

```sh
uv run --project 02_api_backend/full --locked python 01_web_app/tests/identity_smoke.py --checkout
```

This resolves the declared dependencies through uv; it does not assume a
platform-specific interpreter path or another module's pre-existing virtualenv.
The runner uses isolated fixture state and external identity/provider doubles.
Retain its emitted report, screenshots and any traces together with the checkout
revision, dependency-lock hashes and test results. A fixture run contributes only
the web portion of cache/ownership/feedback evidence, not live Google, model or
semantic acceptance. Ordinary browser skips and separately selected integration
cases must remain visible in the report.

Keep run dates, machine availability, approved clip inventory, exact test counts,
source hashes and results in the evidence package outside Git. Record and verify
the selected clean source with the existing release provenance tools. Results
from different PR heads cannot certify one integrated release candidate.

## Real English-video workflow

Before dispatch, choose an approved primary and backup with currently readable
English captions. Follow the ingestion preflight in
[the module 03 procedure](../03_video_ingestion/PHASE2_ACCEPTANCE.md).
Record approvals and per-run caption outcomes outside Git; do not substitute an
unapproved source after failure.

Use the canonical stack, an authorized session and its existing quota ledger.
Follow [the release runbook](../07_testing_deployment/RELEASE_RUNBOOK.md) for
source/image verification, policy validity, admission and operator prerequisites.
Do not establish available quota from planning estimates or copy/reset the ledger.

1. Import through the actual web UI; retain the job ID and observe progress until
   ready. Accepted/queued is not ready. Confirm readable English evidence with
   original timestamps and matching source/version.
2. Exercise chat, summary, compare, research, quiz, flashcards and study plan.
   Compare needs at least two ready sources. Select AI response mode when testing
   generation; distinguish document-only answers and provider-failure excerpts.
3. Test full and floating chat, mobile/keyboard access, topic/source/time changes,
   failure recovery and cancellation. Retain failed and partial outcomes.
4. Save, change and withdraw feedback; reload and verify association with the same
   assistant message. In the admin queue, save notes/outcome then change filters
   and reopen: the save must complete and the stored values must persist.
5. Complete a quiz, inspect score/explanations and reopen its result after reload
   without another submission. Confirm other users cannot read private results.
6. Record actual task/source/version IDs, provider/model provenance, usage and
   queue/HTTP timings. Keep credentials and session cookies out of the package.

Human quality approval, capacity measurements and the other owners' release gates
remain separate requirements. Retain paths and SHA-256 in the release manifest;
passing frontend fixtures alone does not establish stable-main readiness.
