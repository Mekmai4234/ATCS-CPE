# Phase 2: English-video ingestion procedure

Status: procedure only. Real import/embeddings acceptance remains pending until
its evidence is recorded on the chosen release candidate.

## Select and approve sources

Use an approved primary and an independently verified backup:

- Primary: <https://www.youtube.com/watch?v=T-D1OfcDW1M>
- Backup: <https://www.youtube.com/watch?v=IwvdDtN1gs8>

Recheck English captions before each import; availability can change. If either
source is unavailable, propose a replacement, verify it read-only and obtain
approval before importing. Do not silently change sources or synthesize captions.
Keep approval dates, machine details, caption counts/timing/fingerprints and
failed-candidate records in the evidence package outside Git.

## Read-only caption preflight

From `MiniProject`, use the existing tool with the locked module environment:

```sh
uv run --project 03_video_ingestion --locked python 03_video_ingestion/scripts/live_check.py --video-id VIDEO_ID --output 03_video_ingestion/runtime/phase2/caption-check.json
```

Replace `VIDEO_ID` with an approved ID. Select English through
`TRANSCRIPT_LANGUAGES=en` in the chosen local configuration. Keep any metadata
credentials in that configuration, not in the command or evidence output.
The tool performs public caption/metadata reads; it writes no application database
and calls neither embeddings nor generation. Verify `passed`, language `en`,
caption provenance and nonempty normalized timestamped segments in the result.
The last caption end does not establish video duration or complete speech coverage.
A successful preflight does not establish G5 or application-ready state.

## Offline regression

Run from `MiniProject`:

```sh
uv run --project 03_video_ingestion --locked pytest 03_video_ingestion/tests -q -W error -o asyncio_default_fixture_loop_scope=function
```

To retain JUnit, append
`--junitxml=03_video_ingestion/runtime/phase2/ingestion.xml`. Keep the result,
optional local-tool skips, exact source/dependency-lock fingerprints and artifact
SHA-256 together. Fixture coverage includes timestamps/language, empty/invalid
captions, dedup, failures, cleanup and restart; it does not certify real embeddings.

## Canonical-stack acceptance

Follow [the release runbook](../07_testing_deployment/RELEASE_RUNBOOK.md) for
source/image verification, policy validity and quota admission. Use the authorized
canonical stack and its existing ledger; never dispatch against a fresh/copied
ledger to regain quota.

1. Record clean source/image revision and valid policy/ledger readiness with the
   API/RAG/release owners. Use the same approved account and existing counters.
2. Import the primary through the real web UI. Retain accepted job, progress and
   final state. Accepted/queued is not ready.
3. Record English caption/source/version, normalized time fingerprint and stage
   timings. Verify the actual embedding provider/model/dimension and paired index
   receipt before accepting ready state.
4. Read evidence back through the authorized source and run one bounded worker
   question. Check citation intervals, source/version and actual provider usage.
   Verify reimport/dedup and restart using the existing lifecycle guards.
5. Save success and failure/partial outcomes, calls/tokens, timings and hashes
   outside Git. G5 remains pending until the entire real pipeline passes on the
   selected release source; fixture vectors cannot substitute for real embeddings.

Provider pools, keys, billing, shared counters and other modules' source are not
changed by this procedure. Stable-main, public access and deployment require
separate release approval and the full set of matching-source evidence.
