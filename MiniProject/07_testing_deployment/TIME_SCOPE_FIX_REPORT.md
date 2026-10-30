# Video time scope correction — 30 October 2026

## Behavior

- Module 03 parses whole `MM:SS` and `HH:MM:SS` tokens. `01:20:30` selects the point at 4,830 seconds, with a focused window of 4,825–4,845 seconds.
- An explicit continuous range such as `01:00 ถึง 04:00` or `01:00-04:00` is passed as 60–240 seconds. It is not converted into a 20-second window around the first timestamp.
- Ranges of at most 20 seconds use 3 FPS; longer ranges use the existing 0.25 FPS sampled-review mode. Providing the whole requested interval is not continuous inspection of every frame.
- Reversed/equal ranges, invalid clock fields, negative times, incomplete clock tokens, multiple ambiguous times and times beyond two hours produce validation errors. Numbers are length-bounded before integer conversion.
- Module 05 routes clock questions to the native time-aware path even without visual keywords. It validates the time plan before cache/provider access. Explicit windows use a versioned cache key; legacy answers that used the wrong window are not reused by this path. Existing citation records are preserved.
- Module 02 maps time validation failures to HTTP 422. Module 01 displays Thai instructions for correcting the input.

Existing native limitations remain: one source per native call, a 90,000-token admission budget, sampled video evidence, provider availability and project quotas. This change does not increase those limits or certify model answer semantics.

## Verification

| Check | Result |
| --- | --- |
| 01 unit tests | 119 passed |
| 02 full suite | 151 passed |
| 03 full suite and additional malformed-token regressions | 161 full-suite passes plus 2 added passing cases: 163 distinct cases; 2 local-tool checks skipped |
| 05 full suite | 222 passed |
| Checkout identity/browser integration | 8 passed |

Total: **663 distinct passing automated cases**. SDK wire tests inspect actual serialized start/end offsets for hours and explicit ranges, enforce current-question isolation from history, reject out-of-window observations, and check versioned window cache keys. Invalid/ambiguous time cases are checked before a provider or cache can be consulted.

TypeScript/Vite build and scoped Ruff/diff checks pass. Tests use controlled provider responses; no real Gemini calls or additional model quota were required. Existing live-model verification limitations are unchanged.

Ignored logs: `runtime/time-scope-backend.log`, `runtime/time-scope-ingestion.log`, `runtime/time-scope-answers.log`, `runtime/time-scope-identity.log`.
