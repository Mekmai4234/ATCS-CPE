# Proposed member ingestion boundary — 02 / 03 / 04

Status: **implemented 03 boundary; awaiting the 02/04 contract and real adapters**.
This is a proposal, not an agreed database/API migration or a working Google Login
release. Read [MEMBER_REPORT.md](MEMBER_REPORT.md) for exact validation and gaps.

The 2026-10-21 input documents request shared source storage with private libraries/jobs.
At the inspected `develop@69f5347`, 02 still provides the single-user Repository and
ExecutionContext. There are no users/sessions/user_videos migrations or member job
ownership methods. 04 fences generations/leases but does not yet check member refs.
03 must not create an independent authentication or membership database to bypass this.

## Ownership of the implementation

| Owner | Required implementation |
|---|---|
| 02 | Google verification, session/CSRF/disabled-account checks, member identity, private jobs and routes, migration/legacy-owner assignment, atomic library admission and reference accounting, quotas/fair claims |
| 03 | Validate/normalize URL batches, call the trusted member backend, restrict response DTOs, retain timestamped ingestion, guard source delegation and reuse existing bounded subprocess cleanup |
| 04 with 02 | Member-authorized search/read/evidence/inventory plus transactional generation/version/lease/reference fences at index publication and physical GC |
| 01 | Agree on public statuses/DTOs and polling after 02 chooses API routes |

Admin status must not bypass private job/transcript access. No member is selected from
an HTTP user_id/owner_id/role field. Neither a first login nor a deployment migration
automatically grants legacy data or admin rights. This change creates no users and
does not adopt or migrate existing data.

## Injection from trusted server composition

`members.MemberBackend` proposes three synchronous, short backend operations:

1. `require_member(context)`: verify a server-issued session/request context, account
   status and CSRF as applicable. Context is opaque to 03; no attribute named user_id
   or role is accepted as authentication. The principal must be resolved by 02.
2. `execute_member(context, operation, payload, limits)`: recheck authorization inside
   the transaction that performs the operation. Return the DTOs below, never a raw
   application row, session, shared worker job, or another member's result.
3. `authorize_source(context, command)`: return `SourceGrant(command, execution)` for
   the exact shared worker/read/GC operation. A grant is an internal object, never a
   Pydantic model parsed from a client JSON body.

An implementation must declare the exact `CONTRACT_VERSION` and required guarantees
in `members.py`. These declarations detect incomplete wiring; they are **not** a proof
of authorization correctness. Real 02/04 database integration tests remain mandatory.
The test backend under `tests/` is a lock-protected simulation and must not be deployed.

`MemberIngestion(backend, settings)` offers these control-plane calls:

| Call | Backend operation / payload | Output |
|---|---|---|
| `add({"urls": [...]}, context)` | add / normalized distinct video_ids | MemberImports, one result per original input index |
| `job(id, context)` | job / private job_id | MemberJob |
| `job(id, context, operation="retry")` | retry / private job_id | MemberJob, possibly a new private ID |
| `job(id, context, operation="cancel")` | cancel / private job_id | MemberJob |
| `transcript(id, context, limit=100, offset=0)` | transcript / video_id, limit, offset | MemberTranscript |
| `remove(id, context)` | remove / video_id | LibraryRemoval, not physical deletion |

Input import bodies reuse 02's strict ImportRequest, rejecting unknown ownership fields.
Invalid individual URLs are rejected per input index; normalized duplicates are admitted
only once by the backend and expanded to their original positions. Authentication is
required even for a batch containing only invalid URLs. No URL is fetched by these calls.

MemberAdmission returns video_id, a member-private job_id, outcome (added/existing/rejected),
status (importing/ready/no_transcript/failed/rejected), and a classified error_code when
applicable. Rejected admissions have no job. Existing ready sources issue/reuse only
private result records and must not invoke caption/embedding operations. The backend
must return exactly one admission for every unique valid input ID; extra fields/IDs or
missing entries fail with member_contract_invalid_output. DTOs never include raw shared
job IDs, tokens, Google subjects, cookies or free-form provider exceptions.

The proposed vocabulary and routes still need agreement with 01/02; no HTTP router
or existing endpoint shape is changed here. Unknown/foreign private resources should
produce the same generic 404. A backend must not special-case admin to expose contents.

## Atomic shared lifecycle and quotas (02 responsibilities)

Admission is one database transaction per agreed batch policy: authorize, apply quotas,
attach user_videos, select/create the current shared source, and create/reuse a private
job. Concurrent A/B imports must join the same durable source claim, with distinct
member job IDs. Never return the original shared owner's private job to a joiner.

Membership and active job references are separate. Cancel A's job/interest without
cancelling work B still needs. Remove A's library membership without deleting B's
source. GC can be scheduled only after zero member refs **and** zero active dependent
jobs; retain/revalidate generation tombstones for reimport. A still-running cancelled
worker must be fenced and drained before GC can run. 02 decides any retention policy.

`MemberSettings` is separate from existing `IngestionSettings` so 02's FullSettings
field enumeration remains compatible. Defaults (configurable via MEMBER_ variables):

- MEMBER_IMPORT_MAX_URLS=50: 03's per-request URL bound, also passed to 02.
- MEMBER_PENDING_IMPORT_LIMIT=20: durable pending-job admission limit per member.
- MEMBER_RUNNING_IMPORT_LIMIT=2: durable worker-claim limit per member.

The latter two are forwarded to the backend; 03 does not claim to enforce them with
an in-process semaphore. 02 must enforce them across API/worker processes, account for
shared work once according to the agreed policy, and select claims fairly. It must
also resolve the settings once and pass the same configuration to every process.

## Worker/read/GC delegation

`MemberSourceAdapters(inner, backend)` delegates existing ingestion/index/evidence/
inventory/deletion through an exact SourceCommand and a server-issued SourceGrant:

- ingest/index require a shared source worker claim, not A's private member job lease.
- read requires current membership for every explicit video/generation/version;
  knowing a chunk ID never grants scope. Scope is not silently widened.
- delete is explicitly GC, requiring zero refs/dependencies and an exact generation.
  A member remove request never invokes this method directly.

The grant execution checks authorization before delegation and before results return.
IngestionService also calls its check while waiting for captions, preserving cancellation
and the existing no-caption/timeout/cleanup behavior. Generation/scope drift is rejected.

Most importantly, execution.repository._owned() must enforce the same shared-claim,
membership/ref and generation checks **inside** the transaction used by 04's fence.
Checks before/after an async call alone do not close the GC/publication race. All 04
entrypoints, including search/read_video_chunks used by 05/06, need the agreed context.
Wrapping only 03's evidence/inventory methods does not secure those other call paths.

## Activation and release gates

The optional `member_adapters.create_member_adapters` looks for a trusted
repository.member_ingestion_backend. The current Repository does not provide it, so
startup fails with a non-retryable 503 member_contract_unavailable before constructing
RAG/provider clients. There is no silent legacy or fixture fallback.

Do not expose the current single-user API as a member service by changing only an
ADAPTER_FACTORY string. The legacy GET job/transcript/history routes are not protected
by this wrapper. The existing single-user factories remain unchanged for local use.

Before enabling member traffic, 02/04 must agree/implement the contract, protect every
route, implement real user_videos/private jobs/quotas/fair claims, migrate data with an
explicit owner, and integrate the atomic source fence. Then run two-account HTTP and
multi-process DB/Chroma tests for import, ready reuse, foreign reads/retry/cancel,
remove while B reads, active-worker/GC races, generation changes and reimport. Verify
05/06 scope isolation before rollout. Google verification is owned and tested by 02.

No auth secrets, accounts or real member data are created by this proposal. 03 emits
no member/session logs; 02's logs should use minimal internal references and redact
credentials. Privacy is not established by passing the simulation tests alone.
