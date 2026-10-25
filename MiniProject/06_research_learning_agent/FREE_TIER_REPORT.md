# Module 06 Free Tier and media verification

Date: 2026-10-25 (Asia/Bangkok). Base develop: 1814bf3.
Only module 06 files change. Work is isolated in codex/06-free-tier-agent; the original
checkout's 02 feature branch is not modified.

## Common candidate

Unmodified module archives were combined under the ignored 06 runtime/free-tier-candidate
directory with the current 06 source/tests. The same candidate was used on Windows and Docker.

| Dependency | Exact revision |
|---|---|
| 02 PR #27 | b3bb18d960cc664653a8d3be4732112f1c1059b2 |
| 04 PR #29 | b3e983a30a4677b7f344bb09af013fd2cac4f9af |
| 05 PR #26 | 387dfeddb7f5f7db91f455c12ec4b5db67ed855b |
| 03 PR #25, available for composition | dfda16d3b1bd1d2aae7e9c84780095f5fd201916 |

No dependency source/manifest was edited. Core and acceptance lock files already match
these manifests; checked offline/locked resolution introduced no lock or public dependency change.

## Implemented

- All actual 06 Gemini preflight/generation requests use the shared 02 execution broker
  and matching configured credential. Missing verification cannot send countTokens.
- 429 and 503 are normalized before reservation settlement, preserving shared quota
  behavior and redacting provider bodies. SDK retry remains disabled; no fallback is added.
- Per-run model/tool/frame allowances protect finalization and stop expansion. Quota wait
  can return checked local partial evidence or propagate backend pause when no evidence exists.
- Added internal v2 media controller, stored OCR/visual tools, strict frame/source/version
  citations, delegated 05 inspection contract, cache/repeat guards and bounded learning output.
- Native 02/04 image-only lexical retrieval works without any transcript or model invocation.
- Scope, cancellation, deadlines, source checks, packaged dataset and isolated acceptance
  environment remain covered by regression tests. Operational progress includes safe counters.

## Results

| Gate | Result |
|---|---|
| Windows core | 125 passed |
| Windows core + actual 05 comparison acceptance | 129 passed |
| Windows backend/Free Tier contracts | 9 passed |
| Docker core, network disabled, non-root | 125 passed |
| Docker combined acceptance, network disabled, non-root | 129 passed |
| Docker backend/Free Tier contracts, network disabled, non-root | 9 passed |
| Core/acceptance lock --check --offline | passed, locks unchanged |
| Locked environment sync and Docker builds | passed |
| Ruff lint and format | passed |

The SDK HTTP responses, Google claims, image bytes/OCR and provider billing attestations
are fixtures. The shared broker tests use real 02 SQL reservations and roles, including
separate count/generate accounting, missing policy, credential mismatch and 429/503 with
one attempted request. SDK wire-only tests explicitly inject mocked admission and are
not presented as proof of project-wide accounting.

Media tests cover local OCR without transcript, stored descriptions without new vision,
OCR distinct from visual inspection, exact frame/version citations for learning outputs,
unknown frames/citations, revocation, model/tool budgets and repeated-frame suppression.
The native OCR case uses real 02 MediaStore and 04 lexical retrieval. Planning/05 image
expansion tests use explicit synthetic internal bridges; they are not a public media E2E.

An initial Windows run failed importing a deeply nested OpenTelemetry module through the
long candidate virtualenv path, surfaced as Chroma vector_store_error. A direct import
probe reproduced the missing module. Installing the SAME locked environments at the
shorter ignored 06/runtime/c and 06/runtime/a paths fixed the import. No dependency was
removed, test skipped, permission check bypassed or timeout increased to mask that issue.

Local evidence: runtime/free-core-local.xml, free-acceptance-local.xml,
free-contract-local.xml and corresponding free-*-docker.log files. All candidate data,
environments, databases, fixtures and runtime reports stay excluded from the PR.

## Reproduction

Use a common MiniProject candidate containing the recorded dependencies and this 06 tree.
For Windows, point UV_PROJECT_ENVIRONMENT at a short directory for each environment.

```powershell
uv lock --project 06_research_learning_agent --check --offline
uv lock --project 06_research_learning_agent/acceptance --check --offline
uv sync --project 06_research_learning_agent --locked --offline
uv run --project 06_research_learning_agent --locked pytest 06_research_learning_agent/tests -q -W error
uv run --project 06_research_learning_agent/acceptance --locked pytest -c 06_research_learning_agent/acceptance/pyproject.toml 06_research_learning_agent/tests 06_research_learning_agent/acceptance/tests -q -W error
docker compose -p yk06-free-tier -f 06_research_learning_agent/compose.test.yaml build tests acceptance contracts
docker compose -p yk06-free-tier -f 06_research_learning_agent/compose.test.yaml run --rm tests
docker compose -p yk06-free-tier -f 06_research_learning_agent/compose.test.yaml run --rm acceptance
docker compose -p yk06-free-tier -f 06_research_learning_agent/compose.test.yaml run --rm contracts
```

## Remaining shared handoffs

FREE_TIER_AGENT.md specifies the exact limitations. Native media currently uses enrichment
leases; 02 rejects the agent role on that lease, and 05's visual DTO/bridge is still opt-in.
No public multi-step media Agent, automatic 05 DTO conversion or public media learning
publication is claimed. A joint 02/04/05 bridge and publication scope must precede enabling it.

The final-call reserve is local logical allowance/time, not a multi-request project reservation:
02 offers per-dispatch admission. A future atomic planning/final run reservation remains a
shared 02/06 contract; current quota loss falls back to checked local partial output.

No live provider call, billing change, quota/billing verification for a real account,
manual Google login, OCR quality study or whole-system production deployment was performed.
Existing LLM_MODEL remains unchanged; no claim is made that this model is free for any account.
