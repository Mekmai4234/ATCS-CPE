# Module 04 media / Free Tier verification — 2026-10-24

Scope: only module 04. No other module checkout, user dotenv, application data,
billing setting or provider account is modified. This report supersedes earlier
authorization/consumer-lock reports for the current media and quota extension.

## Exact dependency candidate

- Base / unchanged 03/05/06: `1814bf3622eb62f0963da4f682ea31661728907c`.
- Complete backend 02 package/source/metadata/tests:
  `b3bb18d960cc664653a8d3be4732112f1c1059b2` (PR #27).
- Module 04: this branch's working runtime/test files, hashes recorded in the
  candidate report. No package version/consumer-lock change is needed.
- Candidate: `runtime/locked-candidate-4f7165b0fd` (ignored, disposable).

The checker exports the actual 02 package, uses the committed 04 lock, performs an
offline lock check and real `uv sync --locked`, probes installed backend metadata
and Chroma, then tests that installed candidate. It does not substitute PYTHONPATH
over an old package or repair the lock. Docker builds the same source/metadata/lock.
Test containers disable network access and have no provider key. Each phase has a
log; report.json records refs/hashes/exit codes and host suites have JUnit XML.

## Observed results

| Check | Observed result |
|---|---|
| 04 offline lock check, actual locked install, installed backend/Chroma probe | Passed |
| Complete 04 Windows suite, warnings as errors | **157 passed, 1 skipped** in 283.71 s |
| Full offline lock check and actual locked install | Passed |
| 02 core/integration/native full-factory Windows suites | **180 passed** in 157.55 s |
| Same-candidate Docker build and complete 04 container suite | Build passed; **157 passed, 1 skipped** in 244.80 s |
| Host and Docker Ruff lint / format | Passed; 32 Python files |
| Scope, credential-pattern scan, whitespace, runtime/test/lock match | Passed; 33 files matched the candidate, 110 lock packages unchanged |

Docker image ID: `sha256:bab65050f6781bcade02f3c9ddfd5d9dac4583c074a7c272fe4e07854850723d`.
The image's 32 Python files plus uv.lock also match the submitted bytes; hashes are
in `runtime/media-docker-hashes.json`, with scope/lock audit in
`runtime/media-scope-audit.json`.

The focused latest SDK/media test run passed **54 tests, 1 live acceptance skip**
in 39.94 seconds. An earlier pre-final full run passed 152 tests; another pre-final
candidate caught a long-OCR fixture assertion comparing untrimmed input against
02's canonical stripped text. That assertion now compares the actual canonical
input. Only the final completed candidate below establishes the submitted result.

## What the tests exercise

- Image-only OCR publication through real 02 MediaStore with no transcript rows or
  fake transcript_version; Thai literal lookup maps to exact stored frame/time/asset.
- OCR and broker-proven visual observations remain distinct kinds; the actual 02
  citation verifier accepts the emitted provenance. Source frames/descriptions are fixtures.
- Long Unicode OCR is split within the byte cap, retains the complete canonical
  frame citation and deduplicates vector parts.
- New evidence revisions/generations cannot reuse old semantic pointers. Explicit
  v2 transcript snapshots continue through the original transcript hash/index path;
  unsupported mixed frozen scopes are denied.
- Foreign durable jobs and revoked grants are rejected on vector, lexical, index,
cache and evidence paths. Revocation during vector writes prevents publication.
- Every mocked HTTP request has a completed real 02 broker reservation with the
  embedding role and approved endpoint. SDK automatic retries are disabled; actual
  embeddings use single-item embedContent rather than a hidden SDK batch endpoint.
- Cache hits reduce HTTP dispatches, including questions. Identity changes in owner,
  revision, prepared title, purpose, model/dimensions or policy prevent reuse. The
  actual embedding key must match the broker-approved project before HTTP dispatch.
- A 429 after a successful item retains its checkpoint, leaves no published partial
  semantic run and allows local OCR search. A consented synthetic retry reuses the
  first vector; no frame extraction/OCR is repeated. Synthetic cooldown advancement
  is test setup, not a production bypass or a claimed provider reset time.
- Missing verification never dispatches HTTP; a keyless adapter still handles OCR.
  Tampered vector candidates remain integrity errors rather than lexical fallbacks.
- Generation deletion removes media vectors/manifest/cache under the existing 02
  zero-reference/reader fence. Stopped GC removes retired/staging while retaining active.
- Existing transcript, membership, cursor, persistence, failure and maintenance
  regression tests remain part of the complete module-04 suite.

## Limits and dependencies

No real Gemini/vision request, key/billing inspection, model-access test, production
migration or restore, browser login, real YouTube extraction or OCR accuracy test
was performed. The live test now explicitly requires an approved durable 02
execution; the former standalone network opt-in cannot bypass the broker contract.
The fixed model is unchanged, not certified as free for any user's project.

This candidate validates 04 against the **enrichment-only** v2 scope supplied by
02. It does not activate general visual chat/mixed multi-source jobs or certify
03 PR #25/05 PR #26's different factory/broker proposals. Those source refs are not
installed in this candidate. No independent consumer/browser acceptance is claimed.
`whole_system_verified` remains false. Merge/deploy compatible #27 before this 04
release, run the stopped additive upgrade, then have the composition owner wire
the new 04 methods. See FREE_TIER_MEDIA.md for the concrete handoff and operations.

A two-frame synthetic broker/cache fixture occupied 385,024 bytes in application
SQLite, 254,178 bytes in Chroma and 32 bytes in deliberately minimal asset-signature
fixtures after the suite. `runtime/media-resource-sample.json` records the sample.
These are local mechanism-test footprints, not real image/video capacity estimates;
real-frame disk/CPU sizing and server load remain part of 03/07 acceptance.

## Reproduce

From module 04, with Git, uv, Python 3.11 and Docker available:

```powershell
uv run --no-project --python 3.11 python scripts/check_account_contract.py --backend-ref b3bb18d960cc664653a8d3be4732112f1c1059b2 --full-integration --docker-image yk04-media-free-tier
```

`--prepare-only` exports exact inputs without running/repairing locks. Test input
policies/keys and HTTP replies are clearly synthetic and do not authorize any real
provider account. Use the exact reported source files when comparing results.
