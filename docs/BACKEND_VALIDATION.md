# Backend validation — 2026-10-12

## Scope implemented

Backend foundation and migrations; Argon2id/JWT authentication and roles;
batch management/archive; device registration, hashed credentials, rotation,
connectivity and baselines; idempotent ingestion and filtered history; append-only
observations/corrections; deterministic risk, hysteresis and episodes; Gemini adapter,
fixed LangGraph workflow, pgvector migration and scoped retrieval; durable explanation
worker; deterministic priorities with auditable overrides; deduplicated alerts and
truthful mock attempts; audit APIs; periodic monitoring runner; seeded HTTP simulator;
developer guide, hardware protocol and exported frontend API contract.

The original requirements files were preserved. Frontend, physical firmware,
MQTT, real notification providers, regional languages and production deployment
remain later work. There were no commits, pushes, deployments or messages to others.
The directory does not currently have an initialized Git repository; the provided
`.git` directory is a read-only placeholder.

## Test environment and commands

Shell network restrictions prevented a fresh PyPI install (`uv sync` failed DNS
resolution). Tests used installed Python 3.14 packages plus cached FastAPI 0.141.1,
Starlette 1.7.0 and pgvector 0.5.0 copied into `/tmp/majorproject-test-deps`.
`backend/requirements.lock` records 72 consistent dependency versions used for
verification. Fresh installation and Python 3.12 execution were not verified here.

The sandbox also prevents asyncio self-pipe socket wakeups across threads. A plain
Starlette TestClient hung; a standalone minimal cross-thread asyncio reproduction
confirmed the limitation. The test-only `/tmp/majorproject_run_checks.py` runner
caps selector waits at 10ms so queued callbacks progress. Application code is
unchanged by this workaround. Ordinary environments should use `python -m pytest -q`.

Commands used from `backend/`:

```bash
python /tmp/majorproject_run_checks.py tests -q
python -m ruff format --check app tests alembic scripts ../simulator
python -m ruff check app tests alembic scripts ../simulator
PYTHONPATH=/tmp/majorproject-test-deps python -m mypy app scripts
python -m compileall -q app scripts ../simulator
PYTHONPATH=/tmp/majorproject-test-deps python -m scripts.export_openapi
```

The final test suite contains 54 tests. Coverage includes missing/invalid/expired
JWTs, generic credentials, inactive users, roles and vendor resource isolation;
all operational routes rejecting anonymous access; device/user credential separation;
sensor validation and idempotency conflicts; archive, rotation and observations;
normal/rising/stale/missing/warm-up/invalid/baseline-change risk cases; hysteresis;
priorities and override clearing; unresolved-alert uniqueness and acknowledgement;
quality gates, fixed node order, output/citation safety and provider fallbacks;
worker leases and deterministic-result preservation; monitor actor/eligibility;
and migration upgrade/downgrade/schema equivalence.

Final result: **54 passed**, with two upstream deprecation warnings. Formatting
and lint checks passed for 70 Python files; mypy passed for 53 modules. Compilation
and OpenAPI export also succeeded. The local ignored `.env` was then prepared with
permissions 0600, a generated JWT secret and the example Neon URL placeholder.
No secret value is present in documentation or the exported contract.

Gemini tests stub the adapter's `generate`/`embed` boundaries. No real key was
used, no provider network request was verified, and no AI cost was incurred.
The snapshot emits upstream SDK/TestClient deprecation warnings on Python 3.14;
they are not application failures.

## Database checks

Alembic migrations ran successfully through `0004` against isolated test SQLite.
Tests check schema equivalence, downgrade to base and re-upgrade. PostgreSQL DDL,
including `CREATE EXTENSION vector`, vector(768), TIMESTAMPTZ, foreign keys,
event uniqueness and the unresolved-alert partial unique index, was compiled offline.

Core migrations `0001`–`0003` also executed on a **PostgreSQL 18.6 single-user**
instance under `/tmp/majorproject-pg-check`, with no Docker or permanent application
database. Single-user mode was necessary because the sandbox restricts socket I/O.
The instance reached revision `0003` with 14 public tables including Alembic metadata.
SQL assertions verified the recovery-count default, duplicate-device-event rejection,
humidity check constraint and device/batch foreign-key enforcement. Temporary test
rows were rolled back.

The PostgreSQL command was:

```bash
postgres --single -j -D /tmp/majorproject-pg-check postgres \
  < /tmp/majorproject-core-migrations.sql
postgres --single -j -D /tmp/majorproject-pg-check postgres \
  < /tmp/majorproject-pg-assert.sql
```

This machine lacks the PostgreSQL pgvector extension. Migration `0004` was
**compiled, not executed on PostgreSQL**. Neon connection/TLS, live vector search,
HTTP over a real network, production concurrency/load, Gemini calls and physical
hardware remain unverified. These are stated explicitly rather than inferred from
SQLite/ASGI tests. Paste the Neon URL into the ignored `backend/.env` to perform
the remaining integration checks.

## Operational limits

Risk thresholds are configurable demonstration rules, not validated spoilage science.
The default rules cover tomatoes. No gas-specific ppm or remaining shelf-life is
computed. Every assessment requires human review; AI enrichment preserves the
original deterministic history. Notification delivery is mock-only.

Run the monitoring and optional explanation worker alongside the API for ongoing
operations. The monitoring runner has no distributed leader; use one instance.
The login limiter is per process; shared gateway limiting, TLS termination, backups,
observability integrations and load testing belong to deployment hardening.
Archived history remains stored; photo references are metadata, not file uploads.
