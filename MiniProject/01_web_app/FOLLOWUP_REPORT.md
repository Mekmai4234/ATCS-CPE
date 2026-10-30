# Module 01 — Historical citation lifecycle fix

Date: 21 October 2026 (Asia/Bangkok).
Review input: the user's updated `01_web_app.md`, reviewing PR #15 at `b5e16b0`.
Integration base: `origin/develop@6520b4cd2361ce1acd4121a6ea4dd1663c73da10`.

## Reproduction and change

The new Chrome regression reproduced the review finding before the fix: after a
successful source deletion the old answer still had one clickable citation where
zero were expected. The previous test only covered `sources_available=false`
already present in the original response.

- Capture resolved source IDs, generations and indexed versions when submitting a task.
- Retain the originating job ID for immediate 200 answers and polled results alike.
- Invalidate affected historical citations immediately after DELETE is accepted,
  including citations inside quiz, flashcards, study plans and research artifacts.
- Preserve independently valid references to the other selected videos.
- Revalidate historical job availability and source identity on library refresh.
  Missing videos in a partially loaded library are not automatically treated as deleted.
- Never revive an invalidated historical citation after the same ID is reimported.
  New tasks can cite the replacement generation normally.
- Fence late answers using retired source identities, so deleting a source while a
  request is pending cannot publish new live links to the old source.
- Keep answers visible and show a warning if historical job revalidation fails.
- Update explicit demo transport with generations and source-availability metadata.

No backend implementation or API schema changes were required. Latest develop was
merged to keep the existing PR compatible with the team's current backend.

## Verification

Commands are run from `MiniProject/01_web_app` with the pinned dependencies:

```powershell
pnpm typecheck
pnpm test
pnpm test:browser
pnpm format:check
pnpm build
python tests/backend_smoke.py --ref origin/develop
```

The focused regression suite covers deletion/reimport, external deletion,
generation replacement, reindexing, rejected deletion, failed revalidation and a
late answer after deletion. Additional unit checks cover nested artifacts, partial
pagination, unknown source metadata and monotonic historical unavailability.

The backend smoke scenario extends the original real HTTP/API/worker test with
deletion, durable cleanup, reimport and a new answer: old links stay disabled while
the other video and the newly generated answer retain working links.
The fresh fixture database and logs are in ignored
`runtime/backend-check-b6e4dfe019/`; `report.json` records backend commit and exit 0.
No live YouTube/embedding/Gemini provider was called.

Final observed results:

| Check                                    | Result                                                         |
| ---------------------------------------- | -------------------------------------------------------------- |
| TypeScript                               | Passed                                                         |
| Unit/API tests                           | 46 passed across 3 files                                       |
| Chrome browser suite                     | 30 passed; 1 backend-dependent case intentionally skipped here |
| Real API/worker fixture browser scenario | 1 passed separately against develop@6520b4c                    |
| Formatting                               | Passed                                                         |
| Production build                         | Passed                                                         |
| Git whitespace check                     | Passed                                                         |

The successful full browser run used the final source code without concurrent edits.

## Limits

Refresh rechecks currently displayed results; there are no server push notifications
or automatic restoration of browser state after reload. If version identity cannot
be proven, an unavailable server flag is handled conservatively rather than widening
source availability. Existing coverage describes what the task processed originally;
it is not rewritten into a claim that deleted evidence remains available.
