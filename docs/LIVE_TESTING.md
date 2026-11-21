# Live configuration test — 2026-10-12

Both the Neon URL and Gemini API key load successfully from the existing local
`.env`. Credential values and the private hostname were not printed or changed.

Attempts against the configured services produced:

| Check | Result |
| --- | --- |
| Neon SQL connection | Failed to resolve hostname in the restricted execution environment |
| Gemini embedding | Failed on DNS before authentication |
| Gemini structured explanation | Failed on DNS before authentication after the schema fix below |

The sanitized machine-readable result is [LIVE_SMOKE_RESULT.json](LIVE_SMOKE_RESULT.json).
No live migration, vector query or database mutation executed because the Neon
connection could not open. These results do **not** establish that the credentials
are valid or invalid. Provider quota, model availability and actual live response
quality remain unverified. No Gemini success response or incurred usage was observed.

## Issue found and fixed

The original explanation request failed locally before network access because the
Google GenAI SDK 2.9.0 `response_schema` converter only handles string `const`
values; `Explanation.human_review_required: Literal[True]` emits a boolean `const`.
The adapter now derives a provider schema requesting a boolean without `const`.
Application validation retains the strict `Literal[True]` requirement, status checks,
citations and safety guards. The constraints on accepted explanations are unchanged.

New tests exercise the actual SDK request serializer with an intercepted HTTP
transport (no fake provider class or external network), preserve the local True
constraint, redact diagnostics and verify independent provider probes. Alembic now
supports an explicitly supplied connection/schema version table; a transactional
migration regression test verifies that the caller can roll back all test tables.

## Repeat from a normal terminal

After installing dependencies as documented in README, from `backend/`:

```bash
python -m scripts.live_smoke --output ../docs/LIVE_SMOKE_RESULT.json
```

Alternatively, with the installed uv CLI:

```bash
uv run --with-requirements requirements.lock python -m scripts.live_smoke \
  --output ../docs/LIVE_SMOKE_RESULT.json
```

The runner uses synthetic readings/observations in a uniquely named PostgreSQL
schema and an outer transaction. Migration metadata is explicitly scoped to that
schema, so an existing public installation cannot cause public tables to be used.
API/session writes use savepoints; schema, migrations, extension creation if needed,
temporary account and all test rows are rolled back. A public pgvector extension,
if already installed, is reused without being dropped. Real Gemini calls send only
synthetic context. No production user/data is sent to the provider.

The runner checks connectivity, migrations through 0004, pgvector, auth,
idempotent ingestion/history, observations/baseline, deterministic assessment,
the persisted explanation job, real vector distance, retrieval, priorities,
mock alerts/acknowledgement and audit. It returns nonzero if any check fails,
retains partial results and excludes secrets/provider bodies from reports.

## Local checks

Before the SDK fix, the suite passed 58 tests. After the fix, the two actual-SDK
serialization/schema tests also passed; the complete final suite contains 60 tests.
Formatting and lint checks pass. Mypy reports no errors in 54 modules.
See the final check results in the current task response; earlier baseline
validation is retained in [BACKEND_VALIDATION.md](BACKEND_VALIDATION.md).
