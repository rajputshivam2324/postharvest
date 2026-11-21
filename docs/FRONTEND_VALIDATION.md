# Frontend validation — 2026-10-12

The React/TypeScript/Vite workspace integrates with the checked-in FastAPI contract.
It includes public landing/login/signup, an authenticated overview, batches and
device setup, sensor history, assessments, observations, priorities, alerts,
decisions and administrator user/audit views. Signup for both operator and vendor
roles was explicitly requested after the initial PRD; administrator signup is rejected.

## Verified commands

From `frontend/`:

```bash
npm run format
npm run format:check
npm run test
npm run build
npm run test:e2e
```

Unit/component suite: **18 tests passed**. Coverage includes public/protected routes,
safe redirects, failed credentials, vendor controls, logout, in-memory bearer tokens,
late 401 responses from older sessions, query loading/errors/recovery and retained
data after refresh failure, encoded filters and signup password confirmation.

Browser suite: **12 journeys passed**, six on desktop Chrome (1440×1000) and six on
Pixel 7-sized Chrome. These use the actual FastAPI application, Argon2id login and
signed JWTs with a disposable file-backed SQLite database. They verify public and
protected routes, operator evidence/observation/decision/alert flows, administrator
batch/device/baseline/archive setup, both signup roles, vendor restrictions, reload
reauthentication and HTTP 401 recovery. Observation text containing a script tag is
rendered as text. Screenshots of desktop/phone landing and overview were inspected;
the overview reading list was adapted to stacked rows on phones.

Build and strict TypeScript checks pass. The chart is a separate lazy-loaded bundle.
The four font weights are self-hosted. Prettier checks pass; generated API types are
excluded from formatting and can be reproduced by the documented generator.
Impeccable's mechanical detector returned no findings for the changed UI targets.

## Backend changes and verification

`POST /api/v1/auth/signup` takes user ID, password and operator/vendor role, defaulting
to vendor. It uses the existing password hashing, user table, audit transaction,
duplicate constraint and a separate bounded per-process rate limiter. No schema
migration is needed. OpenAPI and frontend types were regenerated.

The focused authentication/signup suite passed **12 tests**, including login after
registration, default vendor role, password hashing, duplicate and invalid fields,
administrator-role rejection, authorization and rate limiting. Full backend
regression suite: **64 passed**. Ruff checks passed; mypy reported no issues in
51 source files. The security route-coverage test now explicitly includes signup
in the public allowlist while continuing to require authentication for every other
application route.

## Environment and limits

Verified with Node 22.20, installed Chrome, and backend Python 3.12. The sandbox's
documented threaded socket restrictions stalled the initial full backend run;
browser/local-server checks ran with approved execution outside the sandbox. The
browser fixture overrides the backend unit-test StaticPool with separate SQLite
connections because real HTTP requests run concurrently. Application database code
was unchanged by this test-fixture fix.

No Neon data, real Gemini calls, physical devices, provider notifications, deployment,
commit or push were used for frontend checks. PostgreSQL-specific signup concurrency
was not separately exercised. SQLite/real HTTP checks establish application wiring,
not production load behavior. The pre-existing TestClient deprecation warning remains.

Tokens stay in memory; reload requires sign-in. Charts are paginated at 200 readings
and annotate loaded observation/assessment pages, up to 20 markers in the visible
span. Photo references are text metadata, not uploads. Public operator signup grants
warehouse-wide access as explicitly requested and must be restricted before a real
warehouse deployment. Risk thresholds remain illustrative and gas measurements
uncalibrated; no food-safety or shelf-life guarantee is made.

The provided `.git` directory is a read-only placeholder, so a Git diff/status was
unavailable. Source review and targeted checks were performed directly on the files.
