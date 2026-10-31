# Identity browser acceptance isolation

`scripts/browser_identity.py --checkout` runs both `web-identity` and
`deployment-identity` projects. Each project receives a fresh API, worker,
SQLite database, Chroma directory and browser processes, then tears them down.
All owner scenarios still run; module 07 no longer imports module 01's test file.

This prevents one owner's unrelated sign-ins from consuming another suite's
IP-scoped login challenge budget. Production authentication, its 30-challenge
limit, session/CSRF checks and provider doubles are unchanged. There is no test
endpoint that resets production limits or bypasses real API routes.

The aggregate report succeeds only when both projects pass and both API/worker
pairs stop. Each project has separate logs, reports and Playwright artifacts, so
the second run cannot erase the first run's failed-test diagnostics. Existing CI
artifact directory globs retain both projects.

Local integrated verification with PR #45: web identity 9 passed, deployment
identity 2 passed, cleanup passed. These use the actual HTTP adapter, SQLite,
worker and authorization routes; Google/model providers are fixtures. They do
not establish live Google login, human semantic accuracy, privacy-copy approval
or an actual production deployment.
