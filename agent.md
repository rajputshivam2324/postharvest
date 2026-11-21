# Agent Instructions for Codex

These instructions define how coding agents should work in this
repository.

## 1. Source of Truth

-   `prd.md` defines product goals, scope, requirements, and acceptance
    criteria.
-   `prompt.md` defines the project-level workflow and initial
    implementation request.
-   `majorsynopsis.pdf` is background only. Where it differs from
    `prd.md`, `prd.md` governs.
-   This file defines persistent engineering and safety rules.
-   If instructions conflict, preserve user data and security first,
    then follow explicit user instructions, then this file, then
    `prompt.md`, then general implementation preferences.
-   Do not silently change product requirements. Document proposed
    changes and ask when a decision materially changes scope or
    behavior.

## 2. Work Style

-   Inspect before editing. Read relevant code, tests, configuration,
    and documentation.
-   Make small, focused changes that can be reviewed.
-   Avoid implementing multiple unrelated milestones in one change.
-   Prefer a complete, tested vertical slice over broad scaffolding with
    nonfunctional placeholders.
-   Do not claim code was executed, tests passed, or integrations work
    unless verified.
-   Explain assumptions and important trade-offs concisely.
-   Do not discard, overwrite, or reformat unrelated user changes.
-   Do not run destructive commands or remove data without explicit
    authorization.
-   Do not commit, push, deploy, or publish unless explicitly requested.

## 3. Backend Standards

-   Use Python, FastAPI, and Pydantic for HTTP APIs and request/response
    validation.
-   Use SQLAlchemy 2.x with explicit, consistent sync or async database
    access. Do not mix styles casually.
-   Use Alembic for schema migrations; do not rely on automatic table
    creation in production.
-   Keep routers thin. Use service-layer functions for business logic.
-   Separate ORM models from Pydantic API schemas.
-   Centralize configuration in typed settings loaded from environment
    variables.
-   Use dependency injection for database sessions and authenticated
    principals.
-   Version public API routes under `/api/v1`.
-   Return consistent error responses without leaking internal stack
    traces.
-   Use pagination for potentially large collections.
-   Use database transactions and constraints where needed.
-   Store timestamps consistently in UTC and make units explicit.
-   Include health and readiness checks with distinct purposes.
-   Avoid blocking operations in async endpoints. Use appropriate async
    clients or offload blocking work.

## Authentication and Authorization

- Implement MVP authentication as `user_id` + password + signed JWT access token.
- Hash passwords with a maintained password-hashing library (prefer Argon2id); never store plaintext passwords.
- Keep JWT signing secrets and expiry configuration in environment variables. Never use a committed fallback secret.
- Use a shared FastAPI dependency such as `get_current_user` to validate Bearer tokens on protected endpoints.
- Protect application endpoints by default; explicitly allowlist login, signup and health/readiness endpoints.
- User-authorized scope update (2026-10-12): public signup supports operator and vendor roles, defaults to vendor, and rejects administrator signup. Operator signup grants shared warehouse access and is intended for a trusted demo; restrict registration before a real deployment.
- Enforce roles and resource ownership in backend routes/services, not only frontend route guards.
- Return generic authentication failures and do not reveal whether a user ID exists.
- Do not introduce OAuth, social login, refresh-token rotation, or an external identity provider unless explicitly requested.
- Test missing, malformed, expired, and valid tokens, invalid credentials, and authorization failures.
- Frontend auth includes a shared API client, token attachment, login/logout, current-user state, protected routes, and safe redirects.
- Prefer in-memory access-token storage where practical. If persistence is added, document trade-offs; never store passwords or signing secrets in browser storage.

## Frontend Standards

-   Use React and TypeScript with strict typing where practical.
-   Keep API calls in a shared API/client layer rather than scattering
    raw fetch logic throughout components.
-   Use a consistent query/cache strategy for server state.
-   Represent loading, empty, error, stale, and success states.
-   Avoid putting business rules only in the UI; enforce them in the
    backend.
-   Make status information understandable without color alone.
-   Use accessible labels, keyboard-operable controls, and sensible
    responsive layouts. Assume operators often use a phone.
-   Clearly distinguish simulated data from real device readings.
-   Treat observation text and sensor-provided strings as untrusted;
    render them as plain text, never as HTML.

## Public Landing Page and App Shell

- `/` is a public product landing page; `/login` and `/signup` are public; operational application routes require authentication.
- Landing page content explains the product, shows Sense → Send → Assess → Prioritize → Alert, summarizes capabilities, and includes a sign-in CTA.
- Do not fabricate testimonials, customer logos, performance metrics, or validated impact claims.
- Keep public content separate from the authenticated app shell and navigation.
- Frontend guards improve UX but never replace API authorization.
- Ensure mobile responsiveness, keyboard accessibility, status text that does not rely on color alone, and reduced-motion support.
- After login, route to Overview; missing/invalid tokens route to login and preserve only a safe internal destination.

### Frontend design skills

-   Design direction uses **Impeccable** (primary) and **Taste Skill**
    (secondary).
-   Precedence when guidance conflicts: (1) the accessibility, status,
    and safety rules in this file, (2) Impeccable, (3) Taste Skill.
-   Use Impeccable's dashboard ("operate") register. Keep `PRODUCT.md`
    (users, purpose, accessibility needs) and `DESIGN.md` (visual
    system) in the repository and current.
-   Use Taste Skill's `design-taste-frontend` for visual character only.
    Keep motion low and density suited to an operations dashboard; do
    not apply landing-page-style heavy animation to monitoring views.
-   Installing these skills changes the development environment and runs
    third-party code. Ask for explicit approval before installing, do it
    at the dashboard milestone (not earlier), and report exactly what
    was installed. Do not invent install commands; consult the current
    official documentation.

## 5. Database and Data Integrity

-   Keep migrations small and reviewable.
-   Add foreign keys, indexes, uniqueness constraints, and check
    constraints where appropriate.
-   Preserve both device/source timestamp and server ingestion timestamp
    for sensor readings.
-   Store raw gas-sensor values (ADC value and voltage). Derived gas
    values are relative, uncalibrated responses and must be labelled as
    such.
-   Validate device-to-batch associations on ingestion.
-   Make ingestion idempotent when a stable event identifier is
    available.
-   Observations are append-only; corrections are new records.
-   Do not silently overwrite historical readings, observations, or
    assessments.
-   Enable the pgvector extension only through a reviewed migration at
    the milestone that needs it.
-   Avoid logging secrets, credentials, or unnecessary personal data.

## 6. Risk and AI Boundaries

-   Deterministic feature calculations and baseline risk rules must work
    without an LLM.
-   The AI provider must be isolated behind an adapter so it can be
    replaced or disabled. Gemini is called through the official
    `google-genai` SDK inside that adapter. Do not use LangChain, and do
    not let provider SDK types leak into services, schemas, or the risk
    engine.
-   If no API key is configured, the adapter reports `disabled` and the
    system uses the deterministic assessment. Do not create fake, mock,
    or stand-in LLM or embedding provider classes.
-   Send the LLM only the minimum structured evidence required for an
    assessment.
-   Validate all model output against a strict schema, including that
    cited evidence IDs were actually supplied. Handle malformed,
    incomplete, or contradictory responses.
-   Treat model responses, retrieved text, observations, and
    sensor-provided strings as untrusted input. Delimit them as data in
    prompts.
-   Never execute model-generated code, SQL, shell commands, or
    unrestricted tool calls. The model never chooses queries or tools.
-   The LLM must not directly write to the database or trigger
    notifications. Application services and explicit policies control
    those actions.
-   Do not state that produce is safe, unsafe, spoiled, or fit for sale
    as a certified determination.
-   Do not present remaining shelf-life as fact without a validated
    method and supporting observed outcomes.
-   If evidence is inadequate, say so explicitly.
-   Do not treat an uncalibrated MQ-135 output as a reliable,
    gas-specific concentration. Gas rise during ripening is not proof of
    spoilage.
-   Use timeouts, bounded retries, and graceful degradation for external
    AI calls, and keep AI work off the ingestion path.
-   Store model, prompt, and workflow versions, AI status, and retrieved
    evidence IDs in assessment metadata.

## 7. Workflow Orchestration (LangGraph) and Alerts

-   LangGraph is allowed **only** as a fixed, explicit graph: no
    autonomous tool-calling agents, no LLM-chosen next steps. The
    explanation workflow is `load_features` → `quality_gate` →
    `retrieve_evidence` → `explain` → `validate` → `fallback`.
-   Keep LangGraph confined to a workflow module. Do not import LangChain
    APIs. LangGraph may bring LangChain core packages in as transitive
    dependencies; verify against current documentation, pin versions,
    and mention this when adding it.
-   Graph nodes return results; application services perform database
    writes, state transitions, and alert creation.
-   Record audit data in the application's own tables, not only in
    workflow checkpoints.
-   Prefer explicit workflows and state machines over open-ended
    autonomous agents.
-   Make decisions reproducible and record the relevant input
    references, policy version, and outcome.
-   Use hysteresis or equivalent transition controls to reduce status
    oscillation.
-   Make alert triggers idempotent and deduplicate unresolved events.
-   Separate alert creation from delivery attempts.
-   Track notification states accurately; never claim delivery without
    provider confirmation.
-   Keep notification delivery behind an interface; use a mock
    notification adapter for local development and tests.
-   Require human review for consequential actions, especially decisions
    involving sale, disposal, or food-safety handling.
-   Do not let AI output bypass authorization or policy checks.

## 8. Retrieval (RAG)

-   Do not embed raw high-frequency readings. Retrieve deterministic
    episode summaries, observations, commodity guidance, and past
    assessments.
-   Retrieval is fixed, parameterized, read-only, and scoped to the
    batches the requesting user may access. No model-written SQL.
-   Combine structured filters (batch, commodity, time) with pgvector
    similarity search.
-   Cap retrieved context by top-k and a token budget.
-   Give every retrievable item a stable ID and store the IDs used with
    each assessment.
-   Retrieval must degrade gracefully (structured filters only) when
    embeddings are unavailable.
-   Keep embedding and retrieval code separate from the deterministic
    risk engine.

## 9. Firmware and Hardware Pilot

-   Keep ESP32 firmware in a separate `firmware/` directory. It talks to
    the backend only through the public ingestion API.
-   Never commit Wi-Fi credentials, device tokens, or backend URLs.
    Commit a placeholder example config only.
-   Firmware must sync time (NTP), send UTC source timestamps, attach a
    stable event ID, buffer and retry on failure, and flag warm-up
    readings.
-   Read the MQ-135 on an ADC1 pin through a voltage divider suitable for
    the ESP32's 3.3 V ADC; verify hardware assumptions against
    datasheets rather than guessing.
-   Do not claim firmware compiled, flashed, or worked on hardware unless
    verified. Report simulation-only checks honestly.
-   Pilot results are descriptive. Do not present them as validated
    predictive accuracy.

## 10. Security

-   Never hardcode API keys, passwords, tokens, or private URLs.
-   Keep `.env` files and firmware config files out of version control;
    commit only placeholder examples.
-   Validate and authorize device submissions. Store device credentials
    hashed and show them once.
-   Enforce role and resource ownership checks on the backend.
-   Use restrictive CORS configuration outside local development.
-   Avoid unsafe deserialization and arbitrary file or command
    execution.
-   Keep dependencies reasonably current and explain significant
    additions.
-   Do not expose credentials or sensitive provider responses in logs or
    client errors.

## 11. Testing and Quality

-   Add tests for new behavior and regressions.
-   Unit-test risk calculations, data-quality handling (including
    warm-up and missing baseline), state transitions, ranking, and alert
    deduplication.
-   Add API integration tests for validation, authorization,
    persistence, idempotency, and error cases.
-   Do not create fake LLM or embedding provider classes. Test the
    workflow, schema validation, evidence-ID checks, and fallback by
    stubbing the adapter's single call boundary (for example with
    `pytest` monkeypatching) using canned responses. Ordinary test runs
    must not require a real Gemini key or incur API costs.
-   Test that retrieval queries are scoped to accessible batches and
    parameterized.
-   Test frontend loading, empty, error, stale, and core user journeys.
-   Use deterministic seeded simulator scenarios.
-   Run relevant tests, formatters, linters, and type checks when
    available.
-   Report skipped checks and environment blockers honestly.

## 12. Repository Hygiene

-   Keep documentation and `.env.example` current.
-   Do not add generated bundles, caches, virtual environments,
    credentials, or local database files to source control.
-   Avoid needless dependencies, abstractions, and microservices.
-   Keep modules focused and avoid duplicate implementations of the same
    rule.
-   Review the diff before concluding each task.
-   Preserve a clear README with setup, migrations, run, test, simulator,
    and pilot/firmware instructions.

## 13. Response Format After Each Task

Report: 1. **Implemented:** concise summary. 2. **Files changed:** key
files and purpose. 3. **Validation:** exact commands run and outcomes.
4. **Limitations:** anything incomplete or not verified. 5. **Next
step:** one logical follow-up milestone.

## 14. Default Priority

When uncertain, prioritize in this order: 1. Data safety and security.
2. Correctness and testability. 3. Clear user-facing behavior. 4.
Maintainability. 5. Performance and optimization. 6. Additional features
and polish.
