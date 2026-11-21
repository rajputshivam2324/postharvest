# Product Requirements Document (PRD)

## Post-Harvest Spoilage Prediction System

-   **Status:** MVP specification (revised)
-   **Version:** 1.1
-   **Audience:** Developer, Codex, project reviewers
-   **Primary stack:** React + TypeScript + Vite, FastAPI (Python,
    Pydantic), PostgreSQL + pgvector, SQLAlchemy 2.x, Alembic, Gemini API
    via the official `google-genai` SDK, LangGraph (fixed workflow graph
    only)
-   **Related document:** `majorsynopsis.pdf` (project synopsis; see
    section 16 for how this PRD differs from it)

### Revision notes (1.0 → 1.1)

- User-authorized frontend scope update (2026-10-12): implement public signup for operator and vendor accounts, defaulting to vendor and rejecting administrator signup. Add `/signup` and `POST /api/v1/auth/signup`. Operator self-registration grants shared warehouse access and is for a trusted demo; registration must be restricted before real deployment. The initial no-public-signup scope is superseded by this request.

-   Added LangGraph (fixed workflow graph) and retrieval over sensor
    evidence (RAG) backed by pgvector. LangChain is **not** used.
-   No fake/mock LLM or embedding provider classes. If no Gemini API key
    is configured, AI features report themselves as disabled and the
    deterministic engine continues.
-   Added the Phase 1 hardware pilot (single ESP32 unit in a carton of
    tomatoes), ESP32 firmware requirements, and a ground-truth
    observation log.
-   Moved ESP32 HTTP integration forward in the milestone plan; split the
    AI milestone into explanation (7a) and retrieval/workflow (7b).
-   Frontend design direction: Impeccable and Taste Skill, subordinate to
    the accessibility and safety rules in `agent.md`.
-   Added a section reconciling this PRD with the project synopsis.

## 1. Product Summary

Build a software platform that monitors produce batches using IoT sensor
readings and helps operators identify batches that may be deteriorating.
The platform collects temperature, humidity, and gas-response readings;
stores historical data; calculates trends and baseline risk; retrieves
relevant evidence; uses an LLM to explain structured evidence;
prioritizes batches for inspection or sale; and records alerts and
decisions.

The initial MVP must work with simulated sensor data before physical
ESP32 hardware is connected. The first physical test (Phase 1 pilot,
section 12) is a single ESP32 unit placed in a carton of tomatoes.

## 2. Problem

Post-harvest produce can deteriorate during storage before visible
spoilage is obvious. Basic environmental logging and fixed-threshold
alerts may not provide sufficient context for comparing batches or
explaining why a batch needs attention.

The product aims to turn sensor readings into understandable, traceable,
actionable information for warehouse operators, farmers, and vendors.

## 3. Goals

1.  Register and manage multiple produce batches.
2.  Ingest and retain timestamped sensor readings.
3.  Visualize current and historical readings.
4.  Calculate transparent sensor trends and baseline risk indicators.
5.  Generate evidence-grounded AI explanations and recommended next
    steps.
6.  Rank batches for inspection or sell-first consideration using
    explicit, explainable criteria.
7.  Record alerts, delivery status, and decision history.
8.  Support a simulator-first workflow, then integrate ESP32 devices.
9.  Remain useful when the LLM or network is unavailable.
10. Capture operator observations as ground truth so future validation
    of risk indicators is possible.
11. Retrieve relevant evidence (window summaries, observations,
    commodity guidance, past assessments) to ground AI explanations.

## 4. Non-Goals for the MVP

-   Guaranteeing that produce is safe to eat or sell.
-   Claiming scientifically validated shelf-life estimates without
    calibration and observed outcome data.
-   Replacing laboratory testing, food-safety procedures, or operator
    judgment.
-   Training a custom machine-learning model.
-   Building a distributed microservice architecture.
-   Allowing an LLM to autonomously perform consequential physical or
    commercial actions.
-   Open-ended autonomous agents or LLM-selected tools. LangGraph is used
    only as a fixed, explicit workflow graph.
-   Supporting every commodity with universal thresholds.
-   Validating predictive accuracy from the single-carton Phase 1 pilot.

## 5. Users and Roles

### Warehouse operator

-   View all monitored batches.
-   Inspect readings, risk assessments, recommendations, and priority
    ranking.
-   Acknowledge alerts, record observations, and record actions taken.

### Administrator

-   Manage users, devices, batch metadata, and system configuration.
-   Review audit logs and integration status.

### Farmer/vendor (future or simplified MVP role)

-   View their own batches and receive understandable alerts.

Role-based access must be enforced on the backend, not only hidden in
the frontend.


### Authentication and Session Model

The MVP uses simple `user_id` + password authentication with signed, expiring JWT access tokens.

- `user_id` is a unique login identifier, not a secret.
- Store passwords only as strong password hashes using a maintained password-hashing library (prefer Argon2id). Never store or log plaintext passwords.
- Provide login/logout flows. Login returns a signed JWT access token with expiry; protected frontend requests send `Authorization: Bearer <token>`.
- Keep the JWT signing secret and token settings in environment variables. Never use a committed default secret.
- Validate JWT signature, expiry, and required claims on every protected request through a shared FastAPI dependency such as `get_current_user`.
- Public API routes are explicitly allowlisted: login, signup and health/readiness checks. All application APIs require authentication by default.
- Enforce roles and resource ownership on the backend, not only in frontend route guards.
- Include a basic role field. Do not add OAuth, social login, refresh-token rotation, or an external identity provider in the MVP.
- Prefer in-memory access-token storage in the browser where practical. If persistence is chosen, document its security trade-offs. Never store passwords or signing secrets in browser storage.
- Logout clears the client token. Document that stateless access tokens remain valid until expiry unless server-side revocation is later added.
- Create an initial administrator only through an explicit bootstrap command or documented environment-based setup; never hardcode credentials.
- Test missing, malformed, expired, and valid tokens, incorrect credentials, duplicate user IDs, and authorization failures.

## 6. Main User Journeys

### Journey A: Register a batch

1.  User creates a batch.
2.  User specifies commodity, quantity, storage location, and optional
    metadata (for example starting ripeness stage and variety).
3.  System assigns a unique batch ID.
4.  A device can be associated with the batch.
5.  A clean-air baseline reading for the device can be recorded before
    the batch is placed.

### Journey B: Monitor a batch

1.  Simulator or device submits readings.
2.  Backend validates and stores readings with timestamps.
3.  Dashboard displays latest values, history, connectivity, and data
    freshness.
4.  Missing, invalid, warming-up, or stale readings are clearly
    identified.

### Journey C: Assess risk

1.  Backend calculates rolling statistics, changes, trend velocity, and
    data-quality indicators over configurable windows.
2.  A deterministic baseline risk engine produces an assessment when
    enough valid data exists.
3.  When appropriate and when AI is enabled, a fixed workflow retrieves
    evidence and passes a compact structured context to the AI service.
4.  AI output is schema-validated and stored with its evidence
    references and timestamp.
5.  If AI is disabled or fails, the system retains the baseline
    assessment and records the AI status.

### Journey D: Prioritize batches

1.  System ranks batches using explicit factors such as baseline risk,
    trend direction, commodity-specific configured rules, and assessment
    freshness.
2.  Dashboard explains the factors that influenced each rank.
3.  Operators can inspect the reasoning and record the action taken.
4.  Ranking is advisory and must not imply that sale is always the
    correct action.

### Journey E: Alert

1.  A defined policy detects a qualifying state transition or threshold
    event.
2.  System creates an alert with a deduplication key.
3.  Notification adapter attempts delivery if configured.
4.  Delivery result is recorded.
5.  Operators can acknowledge the alert.

### Journey F: Record an observation

1.  Operator records a dated observation for a batch (visual condition,
    firmness, visible mould, weight, notes, optional photo reference).
2.  System stores it with observer and timestamps.
3.  Observations appear alongside sensor charts and become retrievable
    evidence for later assessments.

## 7. Functional Requirements

### FR-0: Username/password authentication and protected routes

- Implement `POST /api/v1/auth/login` accepting `user_id` and `password`, returning a signed JWT access token, token type, and expiry metadata.
- Implement `GET /api/v1/auth/me` to return the authenticated user's ID and role.
- Use a shared FastAPI JWT dependency for protected endpoints; public routes must be explicitly allowlisted.
- Use a maintained password-hashing library (prefer Argon2id). Return generic login errors that do not reveal whether a user ID exists.
- Include the authenticated user ID in relevant audit records.
- Do not add refresh tokens, OAuth, social login, or a complex identity provider in the MVP.

### FR-1: Batch management

-   Create, read, update, and archive batches.
-   Store batch ID, commodity, quantity/unit, storage location, creation
    time, status, and optional notes and metadata.
-   Validate required fields and prevent accidental duplicate
    identifiers.

### FR-2: Device management

-   Register devices and associate them with batches.
-   Track last-seen time and connection status.
-   Authenticate device submissions with a per-device credential (shown
    once at registration, stored hashed).
-   Do not trust a device-provided batch ID without verifying its
    association.
-   Support recording a per-device clean-air baseline (see FR-6).

### FR-3: Sensor ingestion

-   Accept timestamped temperature, humidity, and gas-response values.
-   Store the **raw** gas-sensor ADC value and measured voltage. Any
    derived value is labelled as an uncalibrated relative response, never
    as a concentration of a specific gas.
-   Support HTTP ingestion initially; MQTT may be added later as a
    transport adapter.
-   Validate units, plausible ranges, timestamps, device identity, and
    payload shape.
-   Accept and store a device `warming_up` flag and firmware version.
-   Reject or quarantine invalid data with useful logs.
-   Preserve source timestamps and ingestion timestamps.
-   Simulator readings use the same ingestion validation path as real
    device readings.

### FR-4: Historical readings

-   Query readings by batch and time range.
-   Paginate large responses and use suitable database indexes.
-   Handle duplicate submissions idempotently where a stable
    event/device identifier is available.

### FR-5: Dashboard

-   Display batch list, latest readings, data freshness, risk state, and
    priority rank.
-   Display time-series charts, historical assessments, and observations
    on the same time axis.
-   Filter by commodity, location, status, and risk level.
-   Provide loading, empty, error, and stale-data states.
-   Clearly distinguish simulated data from real device readings.
-   Follow the frontend design direction in section 8.


### FR-5A: Public landing page and authenticated application shell

Build a polished, responsive public landing page at `/` that explains the product before login. Include:
- A clear hero headline and concise explanation of the problem and solution.
- A primary sign-in CTA and a secondary link to the product workflow or feature overview.
- A “How it works” section for Sense → Send → Assess → Prioritize → Alert.
- Feature sections for batch monitoring, sensor trends, explainable risk assessments, priority ranking, and alerts.
- A workflow/architecture visual and a truthful limitations note: risk indicators support decisions and are not food-safety certification.
- Responsive header/footer, accessible contrast, keyboard navigation, and reduced-motion support.
- No fabricated testimonials, customer logos, accuracy metrics, or impact claims.

Keep the public landing page separate from the authenticated application shell. The app shell can include Overview, Batches, Monitoring, Priorities, Alerts, Observations, and Settings, but only show implemented routes. Operational pages require a valid JWT. After login, route to Overview. If a token is missing or invalid, redirect to login and preserve only a safe internal destination. Frontend guards do not replace backend authorization.

### FR-6: Risk engine

-   Calculate configurable rolling statistics, deltas, trend velocity,
    and data-quality flags. Window lengths are configuration, not
    constants (the synopsis suggests 6-24 h windows; shorter windows must
    be configurable for demos and the pilot).
-   Exclude `warming_up` readings from risk features.
-   Support a per-device clean-air baseline for relative gas response.
    Without a baseline, flag the gas feature as lacking a reference.
-   Keep calculations deterministic and independently testable.
-   Use commodity-specific configuration where available.
-   Do not treat an uncalibrated gas sensor response as a precise
    measurement of a particular gas.
-   Return "insufficient evidence" when data quality or quantity is
    inadequate (including before the first window has filled).

### FR-7: AI explanation workflow

-   Implement the explanation pipeline as a **fixed LangGraph graph**
    with these nodes in order: `load_features` → `quality_gate` →
    `retrieve_evidence` → `explain` → `validate` → `fallback`.
    -   `quality_gate` stops with `insufficient_data` and skips the LLM
        when data is inadequate.
    -   `validate` checks the Pydantic schema and that every cited
        evidence ID was actually present in the supplied context.
    -   `fallback` keeps the deterministic assessment and records the AI
        failure.
-   The graph returns a result only. Application services perform all
    database writes, state transitions, and alert creation.
-   The AI adapter calls Gemini through the official `google-genai` SDK.
    No LangChain APIs are used or imported.
-   Send only structured, relevant features, retrieved evidence, and
    metadata to the configured Gemini model.
-   Request structured output with risk interpretation, evidence,
    suggested next step, uncertainty, and human-review requirement.
-   Validate all model output with Pydantic and treat it as untrusted
    data.
-   Never allow the model to change database records directly, choose
    queries, or execute arbitrary tools.
-   Use timeouts, bounded retries, and graceful fallback. Run AI work
    outside the request path so it cannot block ingestion or monitoring.
-   If no Gemini API key is configured, the adapter reports `disabled`
    and the graph goes directly to the deterministic fallback. There is
    no fake LLM provider class.
-   Store model/provider, prompt version, graph/workflow version, AI
    status (`ok`, `disabled`, `failed`, `invalid_output`), and retrieved
    evidence IDs with each assessment.
-   The explanation must not state remaining shelf-life as fact and must
    not certify produce as safe, unsafe, or fit for sale.

### FR-8: Assessment and state management

-   Maintain explicit states such as `unknown`, `fresh`, `early_decay`,
    `spoiling`, and `insufficient_data`.
-   Define transition rules and hysteresis to avoid rapid status
    oscillation.
-   Log state transitions and their supporting evidence.
-   Status labels are operational risk indicators, not food-safety
    certifications.
-   Status must be understandable without color alone.

### FR-9: Priority ranking

-   Use a transparent, deterministic scoring/ranking policy as the
    initial baseline.
-   Expose the factors behind the ranking.
-   Keep ranking configurable and testable.
-   Do not let the LLM arbitrarily reorder batches without validated
    criteria.
-   Allow operators to override or annotate a recommendation, recording
    the reason.
-   Ranking is only meaningful with two or more monitored batches.

### FR-10: Alerts

-   Store alert severity, batch, trigger, message, creation time,
    acknowledgement, and delivery status.
-   Prevent repeated alerts for the same unresolved event.
-   Start with an in-app alert log and a mock notification adapter
    behind a notification interface.
-   Add WhatsApp/SMS provider integration (for example Twilio) only
    after the core workflow is tested. Local-language (Hindi/regional)
    alert text is a later enhancement.
-   Never report successful delivery unless the provider confirms it.

### FR-11: Simulator

-   Generate repeatable scenarios: stable conditions, gradual
    deterioration-like trend, sudden temperature excursion,
    stale/missing readings, sensor noise, and device disconnect.
-   Support seeded scenarios for reproducible tests and demos.
-   Clearly mark simulated data in the UI and database metadata.

### FR-12: Auditability

-   Record assessment inputs or input references, rules/prompt/workflow
    version, retrieved evidence IDs, output, state transitions, and
    notification attempts. Audit records live in the application's own
    tables, not only in workflow checkpoints.
-   Avoid storing secrets or unnecessary personal data in logs.

### FR-13: Observations (ground truth)

-   Create and list observations per batch: observed time, observer,
    visual grade or condition, firmness, visible mould, weight, notes,
    optional photo reference, and observation type (for example
    `routine`, `start_condition`, `final_outcome`).
-   Observations are append-only; corrections are new records.
-   Observation text is untrusted input everywhere it is displayed or
    given to an LLM.

### FR-14: ESP32 firmware (Phase 1 pilot)

-   Provide firmware (kept in a separate `firmware/` directory) that:
    -   connects over 2.4 GHz Wi-Fi;
    -   reads a DHT22 (temperature/humidity) and an MQ-135 (analog gas
        response);
    -   syncs time over NTP, because the ESP32 has no battery-backed
        clock, and sends a UTC source timestamp;
    -   posts readings over HTTP(S) at a configurable interval (default
        5 minutes) with a per-device credential;
    -   attaches a stable `event_id` (for example device ID + boot ID +
        sequence number) so retries are idempotent;
    -   buffers readings locally and retries when Wi-Fi or the backend is
        unavailable;
    -   flags readings as `warming_up` during the MQ-135 warm-up period.
-   Wi-Fi credentials, backend URL, and device token live in an
    uncommitted config file; commit only a placeholder example.
-   Hardware notes to verify against datasheets: the MQ-135 is a 5 V
    sensor, so its analog output must be divided down for the ESP32's
    3.3 V ADC; use ADC1 pins because ADC2 is unavailable while Wi-Fi is
    active; DHT22 readings can be unreliable under condensation.

### FR-15: Evidence retrieval (RAG)

-   Do not embed raw 5-minute readings. Instead, generate deterministic
    **episode summaries** per window (statistics, deltas, rise rates,
    quality flags) and retrieve those.
-   Retrievable evidence includes: episode summaries, operator
    observations, commodity storage guidance (for example tomato notes),
    and past assessments with their recorded outcomes.
-   Retrieval combines structured filters (batch, commodity, time range)
    with vector similarity using pgvector in PostgreSQL. Embeddings are
    created through the same Gemini SDK adapter.
-   Retrieval is fixed, parameterized, read-only, and scoped to batches
    the requesting user may access. The model never writes SQL or
    chooses queries.
-   Retrieved context is capped by top-k and a token budget.
-   Retrieved text (observations, guidance, sensor-provided strings) is
    delimited as data in prompts and treated as untrusted.
-   If embeddings are unavailable (no API key), retrieval degrades to
    structured filters only; basic monitoring is unaffected.
-   Every retrieved item has a stable ID that is stored with the
    assessment.

## 8. Non-Functional Requirements

-   **Reliability:** API failures must produce clear errors; AI outages
    must not stop basic monitoring.
-   **Security:** Secrets in environment variables; password hashes if
    password authentication is implemented; backend authorization;
    device authentication; restrictive CORS; input validation.
-   **Maintainability:** Modular monolith with clear separation of
    routes, schemas, services, repositories, AI, workflow, retrieval,
    risk engine, notifications, simulator, and firmware.
-   **Performance:** Paginate history queries and avoid blocking API
    workers with long-running AI calls.
-   **Observability:** Structured logs, health/readiness endpoints, and
    traceable errors.
-   **Testability:** Unit tests for risk calculations and transitions;
    integration tests for APIs and persistence; frontend tests for
    important user flows. AI and retrieval tests stub the adapter's
    single call boundary; they never require a real Gemini key.
-   **Accessibility:** Clear labels, readable status text,
    keyboard-friendly controls, and no reliance on color alone.
-   **Data integrity:** Use migrations, foreign keys, constraints, and
    consistent timestamps (UTC in storage).
-   **Frontend design direction:** Use Impeccable as the primary design
    skill (dashboard / "operate" register, `PRODUCT.md` and `DESIGN.md`)
    and Taste Skill (`design-taste-frontend`) as a secondary visual
    layer, with motion kept low and information density appropriate for
    an operations dashboard. Precedence when guidance conflicts:
    `agent.md` accessibility and safety rules, then Impeccable, then
    Taste Skill. The target user often works on a phone in a warehouse,
    so layouts must work on small screens.

## 9. Proposed Architecture

1.  **React frontend:** UI, charts, forms, API client, query/cache
    state.
2.  **FastAPI application:** versioned REST endpoints, authentication,
    validation, orchestration.
3.  **Application services:** batch workflows, ingestion, assessment,
    prioritization, alerts, observations.
4.  **Repositories / SQLAlchemy:** database access and persistence,
    including parameterized retrieval queries.
5.  **PostgreSQL (+ pgvector):** batches, devices, readings,
    observations, assessments, alerts, evidence chunks, agent/audit
    logs.
6.  **Risk engine:** deterministic calculations and state transition
    policy.
7.  **AI adapter:** Gemini client (`google-genai`) with strict
    input/output schemas; reports `disabled` without an API key.
8.  **Explanation workflow:** fixed LangGraph graph (FR-7) that calls the
    risk engine outputs, retrieval, and the AI adapter.
9.  **Retrieval layer:** episode summaries, evidence chunks, embeddings,
    fixed scoped queries (FR-15).
10. **Notification adapter:** mock implementation first, provider
    integration later.
11. **Simulator:** generates readings through the same ingestion path as
    devices.
12. **ESP32 firmware:** separate directory, communicates only through
    the public ingestion API.

Start as one deployable backend application. Do not introduce
microservices unless a demonstrated need emerges.

## 10. Initial API Surface

Use `/api/v1` as the versioned API prefix. Exact response contracts
should be documented with Pydantic schemas.

-   `GET /health` --- liveness check.
-   `GET /ready` --- readiness check including database connectivity.
-   `POST /api/v1/batches` --- create batch.
-   `GET /api/v1/batches` --- list/filter batches.
-   `GET /api/v1/batches/{batch_id}` --- batch detail.
-   `PATCH /api/v1/batches/{batch_id}` --- update batch metadata.
-   `POST /api/v1/devices` --- register device (returns the credential
    once).
-   `POST /api/v1/devices/{device_id}/baseline` --- record a clean-air
    baseline.
-   `POST /api/v1/readings` --- ingest a reading (device-authenticated).
-   `GET /api/v1/batches/{batch_id}/readings` --- historical readings.
-   `POST /api/v1/batches/{batch_id}/observations` --- record an
    observation.
-   `GET /api/v1/batches/{batch_id}/observations` --- list observations.
-   `GET /api/v1/batches/{batch_id}/assessment` --- latest assessment.
-   `POST /api/v1/batches/{batch_id}/assessments` --- request an
    assessment where authorized.
-   `GET /api/v1/priorities` --- current priority ranking.
-   `GET /api/v1/alerts` --- list alerts.
-   `POST /api/v1/alerts/{alert_id}/acknowledge` --- acknowledge alert.

Do not expose internal stack traces or secrets in API responses.

## 11. Data Model (Initial)

-   `User`: unique `user_id`, password hash, role, active flag, timestamps. Never store plaintext passwords.
-   `Batch`: identifier, commodity, quantity/unit, storage location,
    status, optional metadata (for example starting ripeness), timestamps.
-   `Device`: identifier, batch association, credential hash, last seen,
    status, firmware version.
-   `DeviceBaseline`: device reference, baseline raw gas value, recorded
    time, notes.
-   `SensorReading`: batch/device references, temperature (°C), humidity
    (% RH), raw gas ADC value, gas voltage (V), warming-up flag, source
    timestamp (UTC), ingestion timestamp (UTC), optional event ID,
    simulation flag.
-   `Observation`: batch reference, observer, observed time, type,
    condition/grade, firmness, mould flag, weight, notes, photo
    reference, created time.
-   `EpisodeSummary`: batch reference, window start/end, window
    configuration, deterministic statistics and quality flags, engine
    version.
-   `EvidenceChunk`: source type (`episode_summary`, `observation`,
    `guidance`, `past_assessment`), source reference, optional batch and
    commodity, text, embedding vector (nullable), content hash, created
    time.
-   `RiskAssessment`: batch reference, status, deterministic score if
    available, evidence/features, explanation, recommendation,
    uncertainty, model/prompt/workflow version, AI status, retrieved
    evidence IDs, timestamp.
-   `Alert`: batch reference, severity, trigger key, message,
    acknowledgement, delivery state, timestamps.
-   `DecisionLog`: batch reference, decision type, input references,
    rationale, rule/prompt version, timestamp.
-   `NotificationAttempt`: alert reference, provider, attempt status,
    provider reference, timestamps.

Use SQLAlchemy models and separate Pydantic request/response schemas.
Keep migrations in Alembic. The pgvector extension is enabled by a
migration when milestone 7b begins, not before.

## 12. Phase 1 Pilot: ESP32 in a Tomato Carton

**Purpose:** verify the pipeline end to end on real hardware, observe how
the signals behave, and collect real data with ground truth. This pilot
does **not** validate spoilage prediction: one carton is a single sample.

**Setup:** one ESP32 with DHT22 and MQ-135 in a carton of tomatoes; one
registered batch and one registered device; default 5-minute sampling;
stable power; a backend reachable from the ESP32's Wi-Fi network.

**Protocol requirements:**

-   Burn in the MQ-135 initially and allow a warm-up after every
    power-up; readings during warm-up are flagged and excluded from risk
    features.
-   Record a clean-air baseline for the device before placing it in the
    carton.
-   Record starting conditions as a `start_condition` observation
    (variety, ripeness stage, source, storage temperature).
-   Record routine observations at least daily (condition, firmness,
    visible mould, weight, photo reference) and a `final_outcome`
    observation at the end.
-   If hardware allows, log an ambient reference outside the carton.
-   Expect `insufficient_data` until the configured window has filled.

**Interpretation limits:** tomatoes release gases while ripening, and the
MQ-135 responds to several gases and to temperature and humidity, so a
rising gas signal does not by itself indicate spoilage. Pilot results
are descriptive and must not be presented as predictive accuracy.

**Readiness:** data collection can begin after milestone 4; the
dashboard arrives in milestone 5 and risk features in milestone 6. Raw
readings and observations are retained so later milestones can process
pilot data.

## 13. MVP Acceptance Criteria

The MVP is acceptable when:

1.  A developer can start the system using documented instructions and
    environment configuration.
2.  Database migrations run from a clean database.
3.  A user can create and list batches.
4.  The simulator can submit readings through the normal ingestion path.
5.  Readings persist and appear in the dashboard with timestamps.
6.  Historical charts can be filtered by batch and time range.
7.  Risk calculations have deterministic tests for normal, rising-trend,
    missing-data, invalid-data, and warming-up cases.
8.  AI output is schema-validated; with no API key, or on AI failure, the
    system falls back to the deterministic assessment and records the AI
    status.
9.  Priority ranking shows its factors and is reproducible for the same
    inputs.
10. Duplicate alert triggers do not create an uncontrolled alert storm.
11. Simulated data is visibly identified.
12. Critical decisions and assessment transitions are auditable,
    including retrieved evidence IDs.
13. No shelf-life estimate is presented as fact without suitable
    validation.
14. An ESP32 device (or firmware-equivalent HTTP client) can authenticate
    and post readings through the same ingestion path, and retried
    submissions do not create duplicates.
15. Operators can record and view observations alongside sensor
    history.
16. Retrieval queries are parameterized, read-only, and scoped to the
    user's accessible batches.
17. Automated tests pass without a real Gemini key, and known
    limitations are documented.
18. A responsive public landing page separates public content from authenticated operational pages.
19. `user_id` + password login issues a signed, expiring JWT; protected endpoints reject missing, invalid, and expired tokens.
20. Passwords are stored only as hashes, and backend authorization is enforced.

## 14. Delivery Milestones

1.  Repository foundation, settings, database, health endpoints, tests.
2.  User model, password hashing, JWT login/current-user dependency, protected API tests, and frontend auth shell.
3.  Batch/device models and CRUD endpoints, device credentials.
4.  Sensor ingestion and simulator.
5.  ESP32 firmware (HTTP), observation log, baseline recording, pilot
    runbook. **Pilot data collection can start here.**
6.  Public landing page, authenticated dashboard shell, and historical charts (install and configure frontend design skills first).
7.  Risk features, deterministic rules, and state transitions.
8.  AI:
    -   **7a:** Gemini adapter (`google-genai`), validated explanations,
        `disabled` behavior without a key.
    -   **7b:** pgvector, episode summaries, evidence retrieval, and the
        fixed LangGraph workflow.
9.  Prioritization, alerts, and audit trail.
10. MQTT transport, notification provider (WhatsApp/SMS), local-language
    alerts, deployment hardening.

## 15. Risks and Mitigations

-   **Uncalibrated sensors:** label measurements accurately, validate
    hardware, store raw values, record baselines, and avoid claiming
    gas-specific precision without calibration.
-   **Ripening versus spoilage confound:** record observations and
    starting ripeness; avoid interpreting gas rise as rot without
    outcome data.
-   **Insufficient ground truth / single-sample pilot:** distinguish risk
    indication from validated spoilage prediction; collect observed
    outcomes across more batches.
-   **LLM hallucination:** provide structured evidence, constrain
    output, validate schemas and evidence IDs, and use deterministic
    fallbacks.
-   **Untrusted retrieved text:** delimit as data, scope retrieval, never
    let text select tools or queries.
-   **Framework churn (LangGraph):** keep it behind the workflow module,
    pin versions, and keep audit data in application tables.
-   **False alerts:** use state transitions, hysteresis, deduplication,
    and operator acknowledgement.
-   **Connectivity loss:** show stale readings and preserve device-side
    buffering and retry.
-   **Scope creep:** deliver a working simulator-driven vertical slice
    and the pilot before advanced integrations.
-   **Credential leakage:** use environment variables, `.env.example`
    placeholders, an uncommitted firmware config, and `.gitignore`.

## 16. Relationship to the Project Synopsis

`majorsynopsis.pdf` describes the original concept. Where this PRD
differs, the PRD governs the build. Deviations to document in the final
project report:

-   **Stack:** synopsis lists Flask, Firebase Realtime Database,
    LangChain, and Amazon S3. This build uses FastAPI, PostgreSQL
    (+ pgvector), LangGraph only, and the `google-genai` SDK.
-   **Classification:** synopsis has the LLM classify freshness and give
    days remaining. Here a deterministic engine classifies and the LLM
    explains; "days remaining" is not shown as fact without validation.
-   **Alerts:** synopsis has autonomous Twilio alerts on Red status. Here
    alerts start in-app with a mock notifier and human review for
    consequential actions; provider delivery comes later.
-   **Agentic behavior:** synopsis describes LangChain agents with
    tool-calling. Here it is a fixed LangGraph workflow with no
    LLM-selected tools.
-   **RAG:** added over episode summaries, observations, guidance, and
    past assessments.
-   **Hindi/regional alerts, multi-commodity validation, AWS
    deployment:** retained as later goals; tomatoes come first.

## 17. Open Decisions

These can be decided during implementation without blocking the initial
foundation:

-   Commodity-specific risk configuration beyond tomatoes.
-   Authentication approach for the demo versus deployment.
-   Embedding model and vector dimension.
-   Sources and licensing for commodity guidance documents.
-   MQTT broker and device provisioning approach.
-   Notification provider and budget.
-   Deployment platform.
-   Evidence collection protocol for validating spoilage and shelf-life
    estimates beyond the Phase 1 pilot.
-   Data retention and photo storage approach for observations.
