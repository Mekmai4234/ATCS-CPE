# Integrated RAG Buddy — 25 October 2026

## Integrated changes

PRs 25–31 are reviewed together: 03 local media/OCR; 05 scoped visual consumer; 02 evidence v2/shared Free Tier admission; 01 visual evidence UI/parked jobs; 04 media retrieval/checkpoints; 06 budgeted Agent; 07 release verification/local tools.

Integration fixes are separated by module:
- 01 consumes the actual backend provider codes and paused/wait wire metadata, preserves explicit GET follow-up and labels estimated versus provider-known times.
- 02 exports all seven new answer/vision/agent configuration fields through the existing shared configuration, and its full-factory test doubles accept the actual broker constructor.
- 03 propagates the real RAG provider declaration. Its original silent-clip fixture uses distinct Thai/Latin fonts and a separate bounded fixture-encoding budget on Linux; product decoding limits are retained.
- 05 supplies ExecutionBroker: task-local execution binding, actual 02 SQL reserve/dispatch/settle, credential/model/role fences, per-RPC count/generation usage and shared provider circuits. Research tool analysis keeps the real agent role. Injected external adapters are not automatically labelled local.
- 07 refreshes transitive Pillow consumer locks, declares only actual local doubles in its harness, and updates migration acceptance to schema 0003.

## Verification

Windows Python: 890 passed across 13 suites; 2 opt-in local-engine tests were skipped on Windows and their two real-engine cases passed separately on Linux. The final 02 full suite passed 38 cases after correcting its old fixture signature. The final auth/migration suite passed 11 cases with schema 0003. Lint and format passed.

Frontend: 104 unit cases and type checking pass; 71 ordinary browser cases pass (8 opt-in backend cases are separately gated), 8 targeted visual/native-provider cases pass, 4 strict floating cases pass, and 8 real-HTTP identity/API/worker cases pass. Production build/preview and formatting pass. External Google/model transports in identity acceptance are fixtures.

Linux containers: integrated image builds, native 02/05 SDK/SQL admission passes 5 cases with networking disabled, and real FFmpeg/Tesseract decoding/OCR/cache/corrupt-input acceptance passes 2 cases with networking disabled. Synthetic original media only; no real Gemini/Google billing or production capacity certification.

## Current public application behavior

Google identity sessions, user/admin separation, private libraries, caption imports, grounded chat with timestamps, summaries/comparison, research/learning artifacts, full stored-transcript display and Buddy floating chat remain implemented. The actual free-only live provider path requires an externally verified policy matching the project/key/model/role; absent verification blocks requests rather than silently using paid service.

The new image/OCR backend, scoped image routes, media retrieval, visual consumer and Agent media controller are internal foundations. The public visual-only upload/enrichment-to-chat bridge is not yet fully mounted. UI evidence demonstrations use an explicitly installed evidence adapter; they do not prove an arbitrary YouTube clip without captions works end to end. No false transcript is created. Do not advertise visual-only public chat as complete.

## Deployment and data boundary

This integration does not certify real-account Free Tier status, enable billing, change the configured model, mutate user dotenv credentials, migrate the live SQLite/Chroma pair, or deploy to the user's server. The existing local live store was read as schema 0002 with no active jobs; new code targets 0003. Before cutover, stop the services, take the paired SQLite/Chroma/media backup, run migration and verify operator/release evidence. Never bypass the release gate or invent acceptance booleans.

The historical MiniProject README and main/default branch remain preserved. Detailed current-run reports are retained locally outside tracked runtime data.
