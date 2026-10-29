# Member work recovery and readiness

The normal authenticated client can recover durable work through
`GET /api/member/jobs?limit=50&offset=0&include_completed=false`.
The response is paginated and scoped to the current active member, including for
administrators. It exposes public job state, the original validated request and
source snapshots; adapter configuration, lease tokens and model history are not
returned. `include_completed=true` also allows reopening completed learning work.
Recovery follows existing job IDs with GET, never replays their POST requests.

Login challenges now have separate HttpOnly, expiring cookies derived from each
challenge's CSRF hash. Tabs and idle challenge renewals no longer overwrite each
other. Legacy cookie fallback remains compatible with an already-open login page.
Nonce/CSRF verification, five-minute expiry, single-use consumption and existing
per-IP challenge limits remain enforced. No migration or credential storage is
needed.

`/health` remains API liveness and includes a `worker` object. `/ready` returns 503
when processing readiness is unknown/stale and 200 when a recent worker pulse is
present. `GET /api/worker-status` provides the same status to signed-in users.
Workers write an atomic timestamp sidecar next to their configured SQLite file;
API and worker must share that data directory, as they already share SQLite.
Database filenames including their extensions isolate independent heartbeats.
The freshness window is at least 30 seconds, or the configured lease/poll window
when longer. A worker failure is detected after that bounded window, not instantly.

Validation uses isolated fixture databases, shared-cookie multi-tab login,
challenge replay rejection, account isolation and fresh/stale/absent worker tests.
No paid provider calls are needed for these checks.
