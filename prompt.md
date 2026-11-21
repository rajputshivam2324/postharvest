# Codex Project Prompt

## Project

Build the Post-Harvest Spoilage Prediction System described in `prd.md`.
Follow `AGENTS.md` (or `agent.md` if that is the repository's chosen
filename) for engineering rules. The product uses React + TypeScript +
Vite, FastAPI, PostgreSQL (with pgvector later), SQLAlchemy, Alembic,
Gemini API integration through the official `google-genai` SDK, and
LangGraph as a fixed workflow graph. LangChain is not used.

The first physical test is a single ESP32 unit (DHT22 + MQ-135) in a
carton of tomatoes (the Phase 1 pilot in `prd.md`). `majorsynopsis.pdf`
is background; where it differs from `prd.md`, `prd.md` governs.

## How to Work

1.  Inspect the repository and read `prd.md` and the agent instructions
    before making changes.
2.  Summarize the current repository state and identify existing
    conventions before editing.
3.  Work in small, reviewable milestones. Do not implement the entire
    product in one pass.
4.  Before each milestone, state the scope, files likely to change,
    assumptions, and acceptance checks.
5.  Implement only the approved milestone. Avoid unrelated refactors.
6.  Run relevant formatting, linting, type checks, and tests. Do not
    claim checks passed unless you actually ran them.
7.  Report files changed, commands run, test results, limitations, and
    the next recommended milestone.
8.  If a requirement is ambiguous, choose the smallest safe
    implementation and document the assumption. Ask a question only when
    the ambiguity blocks progress or risks destructive changes.
9.  Never overwrite user work or remove existing files without a clear
    reason and explicit confirmation when destructive.
10. Do not add dependencies unless needed. Explain why each significant
    dependency is introduced, and add AI-related dependencies
    (`google-genai`, LangGraph, pgvector) only at the milestone that
    needs them.

## Milestone Plan (from `prd.md`)

1.  Repository foundation, settings, database, health endpoints, tests.
2.  User model, password hashing, JWT login/current-user dependency, protected API tests, and frontend auth shell.
3.  Batch/device models and CRUD endpoints, device credentials.
4.  Sensor ingestion and simulator.
5.  ESP32 firmware (HTTP), observation log, baseline recording, pilot
    runbook. Pilot data collection can start here.
6.  Public landing page, authenticated dashboard shell, and historical charts.
7.  Risk features, deterministic rules, and state transitions.
8.  7a: Gemini adapter and validated explanations. 7b: pgvector,
    episode summaries, retrieval, and the fixed LangGraph workflow.
9.  Prioritization, alerts, and audit trail.
10. MQTT, notification provider, local-language alerts, deployment
    hardening.

## Architecture Rules

-   Use a modular monolith.
-   Backend: Python, FastAPI with Pydantic schemas, SQLAlchemy 2.x,
    Alembic, and PostgreSQL.
-   Frontend: React, TypeScript, Vite, a consistent API client, and a
    query/cache strategy.
-   Keep route handlers thin. Put business workflows in services.
-   Keep database queries in repositories or clearly separated
    persistence functions.
-   Keep deterministic risk calculations separate from LLM provider
    code.
-   Keep provider-specific Gemini logic (generation and embeddings)
    behind an AI adapter using `google-genai`. No LangChain.
-   Use LangGraph only for the fixed explanation workflow
    (`load_features` → `quality_gate` → `retrieve_evidence` → `explain`
    → `validate` → `fallback`). The graph returns results; services
    write to the database.
-   Keep retrieval fixed, parameterized, read-only, and scoped to
    accessible batches. Retrieve episode summaries, observations,
    guidance, and past assessments, not raw readings.
-   Keep notification delivery behind a notification interface; use a
    mock adapter first.
-   Keep simulator code separate, but send its readings through the same
    ingestion validation path as device readings.
-   Keep ESP32 firmware in `firmware/`, talking only to the public
    ingestion API.
-   Use `/api/v1` for versioned API routes.
-   Store timestamps in UTC and make units explicit.
-   Use environment variables for secrets and runtime configuration.
-   Provide `.env.example` with placeholders only.

## Frontend Design

-   Use Impeccable (primary) and Taste Skill (secondary), with this
    precedence: `agent.md` accessibility and safety rules, then
    Impeccable, then Taste Skill.
-   At the dashboard milestone (not earlier), ask for approval, then
    install and configure both skills following their current official
    documentation. Create `PRODUCT.md` and `DESIGN.md`.
-   Design for warehouse operators and farmers, often on a phone, using
    a dashboard ("operate") register: low motion, appropriate density,
    status readable without color alone, simulated data clearly marked.

## Authentication Requirements

- Implement simple `user_id` + password login with signed, expiring JWT access tokens.
- Hash passwords with a maintained password-hashing library (prefer Argon2id); never store plaintext passwords.
- Add `POST /api/v1/auth/login` and `GET /api/v1/auth/me`.
- User-authorized scope update (2026-10-12): add public `POST /api/v1/auth/signup` and `/signup` UI for operator and vendor accounts. Default to vendor and forbid administrator self-registration. Public operator signup is for a trusted demo because operators share warehouse access.
- Use a shared FastAPI dependency such as `get_current_user` to validate Bearer JWT signature, expiry, and required claims.
- Protect application APIs by default; explicitly allowlist login, signup and health/readiness endpoints.
- Include a basic role field and enforce authorization on the backend.
- Do not add OAuth, social login, refresh tokens, or an external identity provider in the MVP.
- Configure JWT secret and expiry through environment variables; never commit secrets or use a production default secret.
- Test valid, missing, malformed, and expired tokens, invalid credentials, and forbidden access.
- Frontend must include login UI, auth context/provider, shared API client that attaches the Bearer token, protected routes, logout, and safe post-login redirect.
- Prefer in-memory token storage where practical; document persistence trade-offs.

## Frontend Landing Page Requirements

- Build a public, responsive landing page at `/` with a clear hero, sign-in CTA, how-it-works flow, key capabilities, workflow visual, and truthful limitations note.
- Do not fabricate testimonials, customer logos, accuracy figures, or impact claims.
- Keep the landing page separate from the authenticated application shell.
- Operational pages require authentication; only show navigation for implemented routes.
- After login, redirect to Overview. Missing/invalid tokens redirect to login and preserve only a safe internal destination.
- Make landing and login responsive, accessible, keyboard-friendly, and respectful of reduced-motion preferences.

## Product Safety and Prediction Rules

-   Treat LLM output as untrusted and validate it with Pydantic,
    including that cited evidence IDs were supplied.
-   The LLM explains structured evidence; it is not the sole source of
    truth for spoilage status.
-   Do not invent shelf-life estimates or represent risk labels as
    food-safety certification.
-   If data is missing, stale, implausible, warming up, or
    insufficient, return an explicit insufficient-data state.
-   Never assume an MQ-135 response is a calibrated measurement of a
    specific gas without validated calibration. Store raw values.
-   Do not let an LLM execute arbitrary code, SQL, shell commands, or
    unrestricted tools, and do not let it choose queries.
-   AI or network failures must not stop basic monitoring. With no
    Gemini API key, the adapter reports `disabled` and the deterministic
    assessment is used. Do not create fake or mock LLM/embedding
    provider classes.
-   Make alerts idempotent and avoid repeated notifications for the same
    unresolved event.
-   Make the ranking policy explicit, deterministic, explainable, and
    testable.
-   Require human review for consequential recommendations or actions.
-   Treat Phase 1 pilot results as descriptive, not predictive
    validation.

## Coding Expectations

-   Use type hints and clear names.
-   Add docstrings where they clarify non-obvious behavior.
-   Validate inputs at API boundaries.
-   Use explicit error handling and useful structured logs.
-   Avoid giant files, duplicate business logic, premature abstractions,
    and unnecessary agent frameworks.
-   Add database constraints and indexes where appropriate.
-   Write tests alongside implementation. Test AI paths by stubbing the
    adapter's single call boundary (for example with `pytest`
    monkeypatching); tests must not need a real Gemini key.
-   Keep frontend loading, empty, error, and stale-data states in scope.
-   Do not hardcode credentials, provider secrets, thresholds, or
    environment-specific URLs.
-   Avoid exposing stack traces or secrets to clients.

## Standard Implementation Cycle

For each milestone:

1.  Inspect relevant code and tests.
2.  Present a short implementation plan.
3.  Implement the smallest complete vertical slice.
4.  Add or update tests.
5.  Run relevant checks.
6.  Inspect the diff for regressions, accidental generated files,
    secrets, and scope creep.
7.  Summarize results and note any checks that could not be run.

## First Task

Do not immediately generate the whole application.

1.  Inspect the repository.
2.  Read `prd.md` and `agent.md`/`AGENTS.md`.
3.  Propose the target folder structure (including `firmware/` and
    separate areas for risk engine, AI adapter, workflow, retrieval,
    notifications, and simulator) and dependency choices.
4.  Identify the initial database entities and API conventions.
5.  Confirm the milestone plan above with acceptance criteria per
    milestone.
6.  Implement only the project foundation after presenting the plan:
    application entry point, settings, database configuration,
    health/readiness endpoints, test setup, and developer documentation.
    Do not add `google-genai`, LangGraph, or pgvector yet. If user
    approval is required by the current conversation, wait for it before
    implementing.

## Definition of Done

A task is done only when: - Its acceptance criteria are met. - Relevant
tests and checks have been run, with results reported accurately. - New
behavior is documented where needed. - No secrets or unrelated changes
are introduced. - Known limitations and follow-up work are listed.
