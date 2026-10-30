# Video Buddy: video evidence and response speed

Date: 30 October 2026 (Asia/Bangkok).

## Changes by module

| Module | Implemented behavior |
| --- | --- |
| 01 web | Native video citations are labelled as AI analysis of pictures/audio, with time links rather than fabricated transcript references. Polling interval reduced from 1,500 to 750 ms. Video review and expanded retrieval have Thai progress labels. Timeout messages have a matching browser regression. |
| 02 backend | Native observations are stored privately in the existing analysis store. Publication requires the same job/lease's completed vision reservation, approved returned model and input hash. Citation publication rechecks owner, exact source version, stored observation and timestamps. Idle worker polling reduced from 1 to 0.5 seconds. No quota counters are reset. |
| 03 ingestion | Canonical, authorized YouTube input plans support sampled whole-video input and focused windows of at most 20 seconds at 3 FPS. Arbitrary URLs and invalid video IDs are rejected. This path does not require downloading videos, FFmpeg or local OCR tools. |
| 04 retrieval | Complete small-clip context can be read locally without a remote query embedding. Oversized/incomplete clips return to normal retrieval rather than silently using a prefix. Existing permission/version fences remain active. |
| 05 answers | Unsupported ranked results expand through bounded transcript pages, including when ranked search has no hits. Visual/audio questions can use native YouTube understanding, then check speech evidence if video cannot confirm an answer. Other unsupported questions can fall back to video. Five-minute bounded in-process text reuse and one-hour private native reuse reduce repeated inference. Unsupported provider output is discarded, not repaired into factual claims. |
| 06 learning | Visual learning topics can use real native-video observations and retain their distinct citation kind. Unknown observation IDs are rejected. Structured-output/tool decoder schemas omit large `maxItems` hints while local Pydantic limits remain enforced. Learning generation asks for no more questions than its bounded prompt/evidence supports. |
| 07 verification | Module regressions, SDK wire checks, real quota/storage proof validation, browser checks and this release report. |

## Measured behavior

An actual short public YouTube clip in the member library was submitted through the configured Gemini model and the shared quota broker. The returned model was the already allowlisted `gemini-3.6-flash` alias of the configured model. Its two time-linked citations passed backend validation and durable publication.

| Scenario | Measured backend wall time |
| --- | ---: |
| First native question | 9.83 seconds |
| Same question/source/owner from durable native cache | 0.09 seconds |

These measurements include the answer operation, backend validation and publication in a local script. They exclude browser/network/HTTP queue time. They are observations for one clip and question, not a latency guarantee for new questions or long clips. The small-context path additionally removes one remote embedding request when its complete context fits.

The existing verified local policy was extended only to the same model's documented multimodal capability (`vision` role); key, project, tier, approved model aliases, expiry and request/token limits were retained. The official capability documentation and the successful video call support this capability change. Billing was not changed.

## Verification

Run Python module suites in separate processes; their fixture modules share names.

| Check | Result |
| --- | ---: |
| 01 unit tests | 115 passed |
| 01 browser suite | 103 passed initially; the one stale timeout-text assertion was corrected and its case passed on rerun: 104 distinct passing cases, 9 skipped |
| 02 full suite | 144 passed |
| 03 full suite | 143 passed, 2 skipped (local media tooling checks) |
| 04 full suite | 159 passed, 1 skipped |
| 05 full suite + subsequent added native regressions | 207 full-suite passes, plus 3 new passing native cases: 210 distinct cases |
| 06 full suite | 128 passed; the updated decoder/native-learning SDK tests also passed (21 targeted cases) |

Total: **1,003 distinct passing automated cases**, excluding repeated runs. TypeScript/Vite build, Prettier, scoped Ruff and diff checks are also required before delivery.

Tests specifically cover forged quota proofs, another owner's observation references, altered timestamps, fabricated citation IDs, invalid provider JSON, abstentions populated with unsupported statements, out-of-window native observations, cache reuse without a second inference, scoped small-context reads without embeddings and terminal polling behavior. These are contract/correctness checks; fixture successes do not certify the semantic quality of every live model answer.

Ignored local diagnostics are under `MiniProject/runtime/multimodal-*.log` and `native-video-*-result.json`. They contain no API credentials. Live probe conversation/job records are retained with the quota ledger for auditability.

## Observed limits and remaining live verification

- Native video is currently bounded to one selected source per native request, 90,000 counted input tokens, 16 observations and timestamps within the supported two-hour range. Multi-source questions retain transcript retrieval. Above-budget video returns to the bounded transcript path.
- Default video inspection samples at 0.25 FPS. A question containing a timestamp such as `01:20` selects a focused 20-second window at 3 FPS. Neither path is represented as continuous, exhaustive coverage.
- Event observations carry timestamps and the prompt excludes replays/repeated views. This is **not** a deterministic object tracker or a guaranteed whole-video event counter. Exact opening totals cannot be established from sparse samples alone; explicit spoken/on-screen totals may support an answer.
- Audio can be inspected directly for a question. This release does **not** replace the original caption import with a complete new ASR transcript, and does not make captionless imports automatically queryable.
- The existing local-image/OCR viewer remains available. Native YouTube evidence is a separate route; it does not manufacture local image asset IDs or transcript chunks.
- Native video inference was verified live. A live visual-learning probe initially received a provider rejection; decoder schema hints were subsequently reduced and SDK/local learning tests passed. A follow-up live learning probe was blocked by the real project quota, so the corrected visual-learning path still needs a successful provider run when quota returns.
- The local shared Flash policy reached its existing 20-request rolling 24-hour budget (completed/sent/uncertain calls remain counted). The earliest internal allowance was estimated at **30 October 2026, about 18:26 Bangkok time**. This is not Google's reset guarantee or a guarantee that all queued work will fit then. Fresh inference may pause; eligible cached native answers do not require a new generation call. Do not clear the ledger or raise verified limits to get around this.
- Model observations remain fallible. Source-bound citations establish provenance; they do not prove every semantic claim. Human-reviewed video questions are still needed for measured answer-quality acceptance.

## References

- [Google video understanding: YouTube inputs, sampling and timestamps](https://ai.google.dev/gemini-api/docs/video-understanding)
- [Configured model capability documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)

Operationally, keep the existing authenticated frontend, trusted origin, shared quota broker and model-return allowlist. Re-import changed source content to refresh its frozen transcript version. When changing prompt/sampling semantics in a future release, advance the native cache version as well.
