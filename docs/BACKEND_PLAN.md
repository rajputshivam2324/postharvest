# Backend delivery plan

The repository began with `prd.md`, `prompt.md`, and `agent.md` only. The user's
backend-first instruction authorizes completing the backend milestones in order;
the frontend milestones are deferred. There is no Docker database requirement.

## Layout and conventions

`backend/app/` contains `api`, `schemas`, `services`, `repositories`, `db`, `core`,
`risk`, `ai`, `workflow`, `retrieval`, and `notifications`. `backend/alembic/`
owns production schema changes. `backend/tests/` owns automated checks.
`simulator/` sends HTTP to the normal ingestion endpoint; `firmware/` holds the
device protocol/pilot instructions. `docs/` holds setup and policy decisions.

Use synchronous SQLAlchemy sessions and synchronous FastAPI handlers (thread
pool). API routes use `/api/v1`, timezone-aware UTC timestamps, explicit units,
bounded pagination, strict schemas, and a consistent error envelope. PostgreSQL
is the production database; SQLite is a test-only isolation mechanism. AI runs
in a separate worker over persisted jobs, never on the ingestion request.

## Ordered milestones and acceptance

1. **Foundation:** typed settings, Neon URL normalization, sessions, health,
   readiness, migrations, local tests. Reject unsafe/missing configuration;
   never create tables at application startup.
2. **Auth:** User, Argon2id, expiring JWT, login/me, administrator bootstrap and
   user administration. Check invalid credentials, token claims/expiry, roles,
   disabled users and duplicate IDs. No signup or default credentials.
3. **Resources:** Batch and Device CRUD/archive, ownership, hashed one-time
   device credentials, baselines. Check role/resource isolation and conflicts.
4. **Ingestion:** SensorReading, UTC source/ingestion time, warm-up, simulation
   designation, event idempotency, filtered history, repeatable HTTP simulator.
   Check invalid input, wrong device/batch, retries and concurrent constraints.
5. **Pilot records:** append-only Observation and baseline history, human
   corrections and outcomes, device protocol/runbook. Hardware verification is
   separate from backend validation.
6. **Risk:** deterministic configurable tomato policy, windows, coverage,
   relative gas baseline, trend and quality flags, hysteresis, RiskAssessment,
   EpisodeSummary and transitions. Check stable/rising/stale/missing/warm-up
   cases. Thresholds are illustrative, not predictive validation.
7. **AI:** official Gemini SDK, structured schema, disabled/failed/invalid
   output fallback; separate reviewed pgvector migration, EvidenceChunk,
   bounded scoped retrieval and fixed LangGraph workflow. Pin dependencies.
   LangGraph has transitive `langchain-core`; no LangChain APIs in app code.
   Tests stub SDK adapter boundaries and incur no API cost.
8. **Operations:** deterministic priorities with factors, operator annotations,
   deduplicated Alert, DecisionLog, mock NotificationAttempt and durable AI job
   worker. Verify reproducibility, auditability and notification truthfulness.
9. **Delivery checks:** formatter, linter, type checking, unit/API tests,
   PostgreSQL migration checks where possible, documented Neon setup and demo.

Initial entities: User, Batch, Device, DeviceBaseline, SensorReading,
Observation, EpisodeSummary, RiskAssessment, EvidenceChunk, Alert, DecisionLog,
NotificationAttempt, and a durable explanation job. Admin/operator can manage
the shared warehouse; vendor is a read-only own-batch role. All mutations log
the authenticated actor. Device submissions authenticate independently with a
hashed per-device token. Device credentials never authorize human APIs.

MQTT, paid notification providers, local languages and production deployment
are later PRD enhancements. The backend MVP uses HTTP and a mock notifier.
