# Current checkout / UI verification — 24 October 2026

## Source-selection fix

PR22 previously tested `integration.json` source by default, which could hide a later
change. Default PR/push CI now tests the GitHub merge-test/current working checkout
directly: Python, frontend and image build context all use MiniProject in that checkout.
No `git archive`, candidate path or pinned fallback is used in that workflow.

`source.py` records actual HEAD, dirty state and per-file SHA-256 (including uncommitted
source locally), and verifies them after tests. It also rejects pinned archive selection
in the default workflow. Regression changes a marker after the pin: the new marker's
real process fails, old provenance is rejected, and a later in-run mutation is rejected.

The old pinned job is now **manual-only**, separately named `miniproject-pinned.yml`.
Its historical result cannot certify the PR being reviewed. Previous 21/22 October
reports are retained as historical evidence, with links to this report.

## Actual baseline and scope

Review began at PR22 head `ec5b02111a2b451c0503bee77ade3c4219c68733`, which merged
develop `8967c60` into the branch. Modules 01–06 have no diff against that develop.
02–06 member work is now merged; actual checkout 01 is still the legacy workspace.
PR17 head `0745d27` contains the older auth/forest UI and no floating launcher/layered
mascot. PR24 is unmerged and was not overlaid into default checks.

Only 07 and authorized workflow files were changed. No module 01–06 source, actual
user data, provider or public deployment was changed. Final commit/merge-test source
identities and verified digests are supplied by the current PR's CI artifacts.

## Local checks on current source

Windows, Python 3.11.16, uv 0.12.9, Node 24.22.1, pnpm 11.25.0, Chromium 156.0.8078.4,
Docker Linux containers. UTC artifact directory dates beginning 20261023 correspond
to 24 October in Asia/Bangkok.

| Check | Result / limit |
| --- | --- |
| Canonical uv lock --check/--offline and locked sync | Passed directly on actual checkout |
| Upstream Python 02–06 + integration/full | 590 passed |
| Final 07 acceptance + regression + strict auth | 23 + 4 + 11 passed, including 3 source-policy regressions |
| Total Python checks | **628 passed**, with live providers excluded |
| Ruff | Passed after final formatting; initial in-progress run saw one format issue, fixed and lint/format rerun |
| Frontend | typecheck/build passed, 46 unit tests passed; Windows CRLF-neutral format check passed, Linux CI runs normal format check |
| Existing browser | 30 passed, 1 backend-only opt-in skipped; not new-UI or auth E2E acceptance |
| Current real adapter runner --checkout | Explicit **BLOCKED / exit 2**, actual 01 has no identity harness. No pinned source was substituted |
| Fixture visual capture | Home/Chat/Login at 375/768/1024/1440 px, 12 screenshots + 4 traces + built resource/gzip measurements |
| Floating strict interaction contracts | **4 failed at missing launcher entry gate**, later bodies not exercised; not skipped or counted as accepted |
| Production auth factory / HTTPS containers --checkout | Passed on isolated state/internal network; backend schema 0002, cookie/API denial checks; frontend acceptance remains separate |

Current visual observations: no floating launcher or Google button in the captured
legacy fixture views; `/login` renders the legacy workspace. No horizontal Home overflow
was observed at the four widths. The supplied mint references clearly require a new
surface. Screenshot capture is **not** design acceptance, real Google proof or 60fps proof.
The capture JSON always records `accepted=false`, explicit blockers and test environment.

## Deliverables and remaining gates

`FLOATING_UI_ACCEPTANCE.md` maps every requested drag/chat/mascot/auth/visual/performance
probe to evidence or a pending implementation/binding. Four provisional interaction
cases cover drag/click, containment/cancel/resize, keyboard/storage alternatives and
synthetic composer state. Bind accessible names and real threshold/storage contracts
with 01 before accepting them. OS touch/IME/keyboard and real HTTP request counts are
not established by those demo interaction cases.

PR remains Draft. Missing new 01 UI is a product blocker, not permission for 07 to edit
01. Google staging/client ID remains unavailable per the prior user response; real
Google and live provider quality stay pending. Actual-source CI green certifies the
executed regression only, never those blocked acceptance rows.

## Evidence

- `runtime/actual-checkout-20261024.log` and `runtime/20261023T184948763607Z/`: full native regression, 22 acceptance cases before the final policy case.
- `runtime/auth-checkout-20261024.log`: strict auth.
- Later `runtime/*/07-acceptance.log`: final 23 acceptance cases; final Ruff report is separate.
- `runtime/browser-checkout-20261024.log`: legacy browser result.
- `runtime/ui-qa/`: fixture screenshots, traces, resource sizes and blockers.
- `runtime/floating-acceptance-20261024.log`: four missing-entry failures.
- `runtime/browser-identity-*/`: current-source identity BLOCKED report.
- `runtime/yk07-auth-5f47339019/`: actual-source container drill, local TLS only.
- `evidence/ui-checkout-2026-10-24/`: representative legacy captures/summary, clearly not new UI.

Run current commands from README and FLOATING_UI_ACCEPTANCE.md. Use current-head CI
artifacts to verify actual merge-test source and final native test counts; a previous
candidate's green checks are deliberately not reused.
