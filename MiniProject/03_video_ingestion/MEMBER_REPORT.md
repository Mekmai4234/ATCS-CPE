# Module 03 member ingestion report — 2026-10-21

Status: **03's optional integration boundary and tests are implemented locally. The
multi-account service is not enabled and is not complete until 02/04 supply their
member contract.** At validation time, no commit, push or pull request had been made;
publication was subsequently authorized by the user.

Branch: `feature/03_member_video_ingestion`, based on `develop@69f5347`.
Both supplied documents were reviewed: `00_overview.md` and `03_video_ingestion.md`
from the user's Downloads folder. They assign authentication, membership storage and
private jobs to 02 and explicitly require agreement on that contract before wiring 03.
The inspected baseline still has a single-user Repository/ExecutionContext and no
users/session/user_videos migration. Existing 04 generation/lease guards do not supply
the new membership and reference fence. This change does not invent a second auth DB.

## Changes made

| Area | Local change |
|---|---|
| Member orchestration | Added `members.py`: strict import validation, URL normalization/deduplication, original input positions, member-private response DTOs and job/transcript/remove operations delegated to a trusted backend. Request bodies cannot choose user_id, owner_id or role. |
| Dependency gate | Missing or incompatible member backends fail with `member_contract_unavailable`; the old single-user Repository cannot silently activate the member factory. |
| Source operations | Added `member_adapters.py`: exact source/generation/version grants, checks before and after async work, shared-worker authorization and separate read versus physical-GC commands. The underlying 02/04 transaction must still enforce the live fence. |
| Library removal | Member removal delegates reference accounting and reports GC scheduling. It never directly calls physical source deletion. |
| Limits | Added separate MEMBER_IMPORT_MAX_URLS, MEMBER_PENDING_IMPORT_LIMIT and MEMBER_RUNNING_IMPORT_LIMIT configuration. Batch size is checked in 03; durable per-account admission, worker limits and fairness must be implemented by 02. |
| Documentation | Added MEMBER_CONTRACT.md and this report; updated README, .env.example, env.txt, process.txt and step.txt with activation requirements and limitations. |

The existing caption pipeline, timestamps, classified errors and bounded subprocess
cleanup are reused. No dependencies, lockfiles, 02/04 application code or database
migrations were changed. Existing single-user factories and endpoints retain their
current behavior; they must not be exposed as a protected member API.

## Validation

All commands ran from the MiniProject root against the checked-out local packages.
JUnit evidence is stored under `runtime/member-ingestion/` (local, ignored artifacts).

| Suite | Result | Evidence |
|---|---|---|
| 03 ingestion, `pytest -q -W error` | **107 passed** in 34.18 s | ingestion-tests.xml |
| 02 backend regression | **68 passed** | backend-regression.xml |
| 04 RAG regression | **97 passed, 1 skipped** | rag-regression.xml |
| 02 full launcher configuration | **23 passed** | full-config-regression.xml |
| Ruff lint and formatting | Passed | `ruff check` and `ruff format --check` |

The skipped 04 case requires explicit opt-in for live Gemini embeddings
(`RUN_LIVE_EMBEDDING_TESTS=1`); it was not enabled in this run. `git diff --check`
also passed, and all changed/new source and documentation files are under 03.

The 03 suite includes the 78 existing tests and 29 new member cases. New cases cover
two accounts sharing one source while retaining private jobs, foreign/admin access
denial, ready reuse, removal while another member reads, cancellation isolation,
concurrent duplicate admission, quota inputs, spoofed ownership/context, malformed
backend output, source generation/version checks, grant revocation and caption task
cleanup after revocation. Existing tests exercise the local API/worker, temporary
SQLite/Chroma and real subprocess lifecycle with provider doubles.

**Member tests use a lock-protected in-memory contract simulation in
`tests/member_backend_double.py`.** They do not demonstrate Google verification,
real member HTTP routes, distributed transactions, durable quotas or worker fairness.
No live YouTube/Gemini calls or real member data migrations were performed for this
change. Historical live-check reports describe earlier work, not this member release.

## Remaining integration requirements

1. 02 must agree on the contract and implement server-owned sessions/Google identity,
   protected routes, private jobs, user_videos, atomic shared-source admission,
   reference accounting, quotas/fair worker claims and explicit legacy-data ownership.
2. 02/04 must enforce membership, active dependencies and generation/version fences
   inside publication/deletion transactions. Pre/post checks alone cannot prevent a
   concurrent GC/publication race. Other 04 read/search paths also need authorization.
3. After wiring, run real two-account HTTP and multi-process database tests, including
   removal/reimport/GC races, foreign retry/cancel and 05/06 scope isolation.

The member factory intentionally refuses activation until its trusted backend is
available. Passing these tests is evidence for the 03 boundary and regressions, not
approval to deploy a multi-account service. See MEMBER_CONTRACT.md for the proposed
operation payloads, DTOs and release gates.
