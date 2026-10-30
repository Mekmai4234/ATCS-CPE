# Module 05 visual / Free Tier verification — 2026-10-24

Base: `develop@1814bf3622eb62f0963da4f682ea31661728907c`.
Only `MiniProject/05_ai_answers_analysis` is changed. No sibling branch is merged.
The 03-local-v1 mapping is tested with labelled DTO fixtures matching the inspected
`origin/codex/03-local-media-ocr` contract, without claiming a production 02 integration.

## Results

| Check | Result |
|---|---|
| Full module 05 offline suite, warnings as errors | 199 passed |
| Targeted visual/SDK/acceptance suite | 88 passed |
| Ruff lint (`src tests scripts`) | Passed |
| Ruff format check (`src tests scripts`) | Passed, 27 files |
| `uv lock --check` | Passed, 115 resolved packages; lock unchanged |
| Wheel build to ignored runtime/visual-dist | Passed |
| `git diff --check` | Passed |

During development an SDK test caught error-precedence regression for a malformed
response without modelVersion. Validation order was corrected so invalid output remains
invalid_model_output while valid output from an unverified alias is quota_pending.
An earlier full run passed 196 tests; the final run includes three additional quota/
vision error tests and the final citation rendering changes.

Executed from module 05:

```powershell
python -m uv run --project . --extra team --locked pytest tests -q -W error -x
python -m uv run --project . --extra team --locked pytest tests/test_visual.py tests/test_gemini.py tests/test_acceptance.py -q -W error -x
python -m uv run --project . --extra team --locked ruff check src tests scripts
python -m uv run --project . --extra team --locked ruff format --check src tests scripts
python -m uv lock --check
python -m uv build --wheel --out-dir runtime/visual-dist
git diff --check
```

## Evidence covered

- Silent cooking fixture yields distinct OCR/visual provenance, original OCR, frame/time,
  generation/evidence version, image API locator and sampled-only coverage. Provider
  observations are scripted, not actual recognition of a cooking image.
- 03-local-v1 handoff maps private asset keys only through an authorized bridge;
  unsafe file/external/token paths are rejected and no transcript_version is fabricated.
- Repeated observation reuses persistent SQLite across service restart. Concurrent
  observations within one service are deduplicated. Owner/grant/generation/version,
  OCR and pinned returned-model changes require separate entries.
- Current permission is checked on cache hits. Revoked/replaced grants or changed
  frame state during generation prevent cache publication; foreign snapshots, changed
  hashes and fabricated citation IDs are rejected.
- OCR injection remains user evidence separate from the system policy in service tests
  and actual SDK wire payloads. Face/Jay and unlabelled performer fixtures refuse before
  provider calls. These are boundary tests, not proof of semantic prompt-injection safety.
- Authorized existing OCR is searched before any new image. Empty/unclear evidence
  produces explicit insufficient_evidence, with no fabricated fallback. At most three
  additional frames are accepted per question.
- Real Google SDK with HTTP mocks sends inline bytes and structured schema, preserves
  requested/returned model metadata and avoids unsupported thinking settings.
- Missing broker, expired verification, mismatched key, false Free Tier attestation and
  missing image capability fail before any HTTP. Expiry after count blocks generation.
- Each count/generate RPC has a broker reservation; actual usage is recorded. Changed
  returned aliases block publication. The injected SDK client is configured for four
  retries in tests; per-call overrides still produce exactly one attempt per RPC.
- Generation 429/503 in the image path retain generation_rate_limited /
  generation_provider_busy, not insufficient_evidence. Truncation, malformed JSON,
  citation, cancellation, private history, partial coverage and settings regressions
  remain covered by the full suite.

## Limits and release status

No live Gemini request, billing/account verification, real image/video understanding,
server deployment or frontend image display was tested. The tests use an explicitly
offline broker double and trusted bridge double; neither is a real shared quota service
or an implemented 02 visual authorization/publication contract. The test image bytes are
labelled fixture bytes, not a decoded real photograph. Existing ASGI/SQLite/Chroma and
worker integration tests still use actual local mechanisms and offline provider doubles.

The new consumer is not mounted on HTTP. Live 05 SDK requests require the real broker,
so current live text generation is blocked quota_pending until upstream integration.
The 02 backend must implement pause/resume semantics for that code; this PR does not
claim queued quota recovery. Full-team embeddings/Agent outside 05 also need broker
integration before any system-wide Free Tier release. See VISUAL_HANDOFF.md.
