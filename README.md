# Harvest Monitor

Harvest Monitor is a post-harvest monitoring system for tracking produce batches
from storage and transport through inspection. It combines environmental sensor
readings, operator observations and configurable rules to surface batches that may
need attention. The current physical pilot is a small tomato box monitored by an
ESP32, DHT22 and MQ-135; the software also supports simulated devices for repeatable
development and demos.

The system is designed to support inspection and record keeping. Its default tomato
rules are illustrative and have not been calibrated against a controlled spoilage
study. An MQ-135 is a broad gas-response sensor: readings alone do not establish
spoilage, identify a gas concentration, predict shelf life or determine food
safety. Compare trends with actual condition observations and have a person review
handling decisions. See [the tomato-box pilot guide](docs/TOMATO_BOX_PILOT.md).

## What is in the project

| Component | Purpose | Main technologies |
| --- | --- | --- |
| `frontend/` | Sign-in, batch and device setup, sensor history, observations, assessments, priorities, alerts and administration | React, TypeScript, Vite |
| `backend/` | Authentication, batch/device APIs, sensor ingestion, monitoring, deterministic assessments, audit and optional AI workflow | FastAPI, SQLAlchemy, Alembic, PostgreSQL, pgvector |
| `sketch_oct15a/` | Physical ESP32 firmware for authenticated HTTP readings, connectivity checks, retry handling and sensor diagnostics | Arduino framework, ESP32 |
| `simulator/` | Deterministic sensor scenarios for local API demos and validation | Python |
| `docs/` | API contract, product plans, pilot procedures and validation notes | Markdown, OpenAPI |
| `prd.md`, `prompt.md`, `agent.md` | Product requirements and project working context | Markdown |

### Data flow

```text
ESP32 or simulator ── device-authenticated readings ──> FastAPI ──> PostgreSQL
                                                           │
Operator observations ────────────────────────────────────┤
                                                           ├─> risk assessment, priorities, alerts, audit trail
React web app <──────── user-authenticated JSON API ───────┤
                                                           └─> optional evidence retrieval and Gemini explanation
```

Sensor devices use their own credentials and submit idempotent readings with a
source timestamp, event ID, sensor values, simulation/warm-up flags and firmware
version. Users authenticate separately with a password and expiring access token.
The backend stores source and ingestion times, keeps observations and assessments
for traceability, and never treats an AI explanation as a replacement for the
deterministic result.

## Quick start

Use Python 3.12 or newer, Node.js 22.18 or newer, and a PostgreSQL database (Neon
is supported). Configure the backend first using [the backend setup](#start-with-neon); then start the frontend using [the frontend setup](#start-the-frontend).
Create the first administrator with the CLI, sign in, and create a batch. The
interactive API reference is available at `http://127.0.0.1:8000/docs` in local
development.

For a physical sensor, follow [the firmware setup](sketch_oct15a/README.md) and
[pilot runbook](docs/PILOT.md). Keep Wi-Fi credentials, device tokens, database URLs,
JWT secrets and provider API keys in ignored local configuration files. Never
commit `backend/.env` or `sketch_oct15a/config.h`.

## Current pilot status

The ESP32 firmware targets an ESP32 Wroom DevKit, with DHT22 on GPIO 4 and the
MQ-135 module output connected through the existing voltage divider to ADC1/GPIO
34. It sends readings every five minutes to the backend. The ADC reports the
voltage at the ESP32 pin after the divider; it does not calculate gas concentration
or infer the module-side voltage. Health checks and HTTP ingestion confirm network
connectivity and data receipt only, not sensor calibration.

The pilot procedure requires the MQ-135's initial conditioning in ventilated room
air, verification of a stable reference, recording a clean-air baseline, and then
placing the assembly with the tomatoes while collecting periodic visual-condition
observations. Firmware warm-up remains explicitly enabled until conditioning and
baseline steps are completed. The detailed current stage, wiring notes, procedure
and known limitations are in [docs/TOMATO_BOX_PILOT.md](docs/TOMATO_BOX_PILOT.md).

## Application capabilities

The API and web workspace provide:

- Role-based admin, operator and vendor access, with hashed passwords and
  separately scoped device credentials.
- Batch ownership, device provisioning and credential rotation, clean-air
  baselines, sensor history and append-only observations.
- Configurable deterministic assessments with data-quality gates, per-device
  coverage, missing/stale data handling, explicit warm-up treatment and recorded
  policy versions.
- Inspection priorities, operator overrides, deduplicated alerts, acknowledgements
  and audit records.
- Optional asynchronous Gemini explanations grounded in retrieved evidence, with
  structured-output validation and a deterministic fallback.
- A simulator with stable, deterioration, temperature excursion, stale, missing,
  noise and disconnect scenarios.

Start-up, API, risk-policy, AI and verification details follow below. The full
product requirements are in [prd.md](prd.md), the OpenAPI contract is
[docs/openapi.json](docs/openapi.json), and operational setup notes are in
[docs/PILOT.md](docs/PILOT.md).

## Start the frontend

With the backend running on `127.0.0.1:8000`, open another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Use Node.js 22.18 or newer (Node 22.20 was verified). Open the local URL printed
by Vite, normally `http://127.0.0.1:5173`. The public landing page is at `/`, login
at `/login`, signup at `/signup`, and the protected workspace at `/app`.
The development server proxies `/api` to FastAPI, so local development needs no
additional CORS configuration. `frontend/.env.example` documents an alternative
proxy target and `VITE_API_BASE_URL` for a separately hosted API. Public Vite
variables must never contain secrets.

The workspace includes an overview with inspection priorities, latest readings and
setup shortcuts; searchable batches; device provisioning and clean-air baselines;
batch sensor history and assessments; append-only observations; priorities and
operator overrides; alerts and delivery attempts; and administrator user/audit views.
Operators and administrators can share a batch with a vendor by setting its owner
(see `GET /api/v1/vendors`). Vendor signup creates an empty read-only workspace until batches are
assigned. Simulation, warm-up, backend device freshness, AI status and uncertainty
remain explicit. Charts show up to 200 readings per page and the loaded observation
and assessment pages as timeline markers; use pagination for older records.

Access tokens are held in memory, not browser storage. Reloading or closing the page
requires sign-in. Expiry and backend HTTP 401 clear the session and cached records;
logout does the same. AI explanations and all observation/device strings render as
plain text. There is no demo login or fabricated operational data in the app.

Frontend checks:

```bash
cd frontend
npm run format
npm run format:check
npm run test
npm run build
npm run test:e2e
```

`test:e2e` requires the installed backend virtual environment and Chrome. It starts
the actual FastAPI API on port 8011 with a disposable SQLite database and Vite on
4173, verifies desktop and phone flows, then stops both servers. It never loads
`backend/.env`, contacts Neon/Gemini, or sends notifications. Set `CHROME_PATH` if
Chrome is installed elsewhere. Production hosting must serve `frontend/dist` with
SPA fallback to `index.html` and route `/api` to FastAPI (or configure its public
base URL plus restrictive CORS). Vite's development proxy is not production hosting.

API types come from `docs/openapi.json`. After backend contract changes, run
`python -m scripts.export_openapi` from `backend/`, then
`python3 scripts/generate-api-types.py` from `frontend/`.

### Seed a batch for AI testing

On **Batches**, operators/admins can click **Seed demo batch**. This creates a
separate `DEMO-TOMATO-*` batch with a simulated device, a clean-air baseline,
seed-42 readings covering the configured risk window, two synthetic observations,
and a deterministic assessment. With the default six-hour policy there are 73
readings. Its simulated nature is visible in the batch list, sensor history,
notes and evidence. Existing batches and history are retained. Vendors cannot seed
records; administrators still provision real devices.

If Gemini is configured, the assessment queues an explanation. Keep the worker
running (`python -m app.worker` from `backend/`) and open the batch's **Assessment**
tab to review AI status, output and evidence citations. Without a key, it reports
disabled and retains the deterministic result. The dataset uses illustrative
environmental exposure and rising gas response, not a model of actual spoilage.

For an explicit CLI seed using the existing oldest active admin account:

```bash
cd backend
source .venv/bin/activate
python -m scripts.seed_demo --explain
```

Use `--user-id YOUR_EXISTING_OPERATOR_ID` to select another eligible account.
`--explain` processes only the new assessment, not the other queued jobs, and
makes real configured Gemini calls. Seeds grow stale over time; create a fresh
demo for another full-window assessment rather than relabelling old evidence.
To retain the same fresh demo and record another assessment, use
`python -m scripts.seed_demo --batch-id DEMO_BATCH_UUID --explain`.
Restart a backend process that was started before the demo endpoint was added.
Restart the explanation worker as well to load the `explanation-v2` prompt and
bounded Gemini 2.5 Flash thinking budget, which leave room for complete JSON output.

The approved design skills were installed locally in `frontend/.agents/skills`:
Impeccable 4.5.2 (engine 0.1.14, no hooks) and Taste `design-taste-frontend`.
These checkout-local installations are ignored. Product and visual decisions are
documented in [PRODUCT.md](frontend/PRODUCT.md) and [DESIGN.md](frontend/DESIGN.md).
See [frontend validation](docs/FRONTEND_VALIDATION.md) for verified coverage.

## Start with Neon

Use Python 3.12 or newer (3.12 recommended). From the repository root:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
test -f .env || cp .env.example .env
```

Edit **`backend/.env`** locally. Set `DATABASE_URL` to your Neon PostgreSQL
connection string. This workspace already has a private `.env` with a generated
JWT signing secret and a placeholder database URL. For a fresh copy of the project,
replace the example `JWT_SECRET` with a new random value. Generate one with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

The example JWT value is deliberately rejected. `.env` is ignored by version
control. Standard `postgresql://` Neon URLs are normalized to the synchronous
psycopg driver while preserving TLS and channel-binding options. Keep
`sslmode=require` (or stronger verification). A pooled Neon URL is appropriate
for the API. Run `alembic upgrade head` on the **direct** (non-pooled, no `-pooler` in
the host) URL: the pooler can leak session state such as `search_path` during
migrations. Pick the Neon region closest to where the API runs; every query is a
network round trip, and a far region makes each page take seconds. See [Neon's SQLAlchemy guide](https://neon.com/docs/guides/sqlalchemy).

Keep `GEMINI_API_KEY` empty to start with deterministic monitoring. No fake AI
provider is used. After configuration:

```bash
python -m alembic upgrade head
python -m app.cli create-admin --user-id YOUR_ADMIN_ID
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

The bootstrap command prompts for a password and confirmation; it does not accept
a password in shell arguments or create default credentials. Repeating a user ID
returns a conflict. Visit `http://127.0.0.1:8000/docs` in development for interactive
API documentation. `/health` checks process health; `/ready` requires database
connectivity and migration `0006`. Tables are never created at API startup.

Run the monitoring process in another terminal, using the same environment:

```bash
cd backend
source .venv/bin/activate
python -m app.monitor --actor-user-id YOUR_ADMIN_ID
```

It assesses active monitored batches every five minutes, including missing/stale
devices, and records the administrator as actor. `--once` performs one cycle;
`--interval-seconds` configures cadence. Explicit assessment requests also work.
Use one monitoring runner per warehouse; there is no distributed scheduling leader.

## Authentication and roles

`POST /api/v1/auth/login` takes JSON `{"user_id": "...", "password": "..."}` and
returns an expiring JWT and the verified user profile in `user`, so sign-in needs
one request. Use `Authorization: Bearer TOKEN` on user APIs. `GET
/api/v1/auth/me` verifies the token and the user's current active flag and role.

- **Admin:** everything an operator can do, plus user provisioning/disable, guidance
  import, full audit access and handing a batch to any user.
- **Operator:** shared warehouse monitoring, batch management, device
  registration/disable/credential rotation and batch assignment, baselines,
  observations, assessments, alert acknowledgement and operator decisions.
- **Vendor:** read-only access to batches explicitly owned by that user, and to the
  devices that have served those batches.

Operators may share a batch with an active vendor; only admins can hand a batch to
any other user. At the user's request,
`POST /api/v1/auth/signup` now accepts `user_id`, a 12–128 character password, and
`role: "vendor" | "operator"` (default vendor). It returns the created user with
HTTP 201; login issues the JWT. Signup rejects administrator roles and extra fields,
hashes passwords, records self-registration, and has a separate per-process rate
limit. Duplicate IDs return HTTP 409. Public operator signup grants shared warehouse
access, so this configuration is for a trusted demo; restrict registration at the
deployment boundary before exposing a real warehouse. No OAuth or refresh token
is implemented. Deactivating a user blocks their existing tokens.
Frontend logout clears the client token; otherwise stateless access tokens
remain valid until expiry. Login has a bounded per-process rate limit; configure
a shared gateway limit when deploying multiple API workers. Public development
docs contain schema only and are disabled in production. Health/readiness and
login/signup are public; ingestion uses independent device credentials.

## End-to-end simulator demo

In `/docs`, sign in, use the returned JWT with **Authorize**, then:

1. `POST /api/v1/batches`: choose a unique identifier, commodity **`tomato`**,
   quantity/unit and storage location. Save the returned batch UUID.
2. `POST /api/v1/devices`: supply an identifier and `simulated: true`. Optionally
   pass `batch_id` to assign it immediately; otherwise assign it later with
   `POST /api/v1/devices/{id}/assignment`. Save the device UUID and its one-time
   credential. The credential is stored only as a hash; reading device details never
   returns it again.
3. `POST /api/v1/devices/{id}/baseline`: use `gas_adc: 1000` and a timezone-aware
   `recorded_at` earlier than the simulator's entire window (at least seven hours
   ago with default settings). Baseline history is append-only.
4. Optionally record a `start_condition` observation.
5. Set `DEVICE_TOKEN` locally to the returned device credential; set
   `ACCESS_TOKEN` to your user JWT if using `--assess`. Then run:

```bash
python ../simulator/send.py \
  --device-id DEVICE_UUID --batch-id BATCH_UUID \
  --scenario stable --seed 42 --assess
```

Default output contains 73 simulated samples at five-minute intervals, covering
six hours. `deterioration`, `temperature_excursion`, `stale`, `missing`, `noise`
and `disconnect` scenarios are also supported. Register a separate batch/device
for each scenario to avoid mixing histories. The deterioration scenario is a
synthetic pipeline exercise, not a model of real spoilage. To retry exactly,
reuse the printed `--run-id` and `--start` with identical arguments.

### A week of simulated history

`scripts/seed_week.py` builds one new tomato batch with seven days of five-minute
readings, so every screen has something to show. It goes through the application's own
services with the clock set to each moment it describes, so the assessments, state
changes, alerts and priorities come from the real rules. The story: steady cold-room
readings, a short Wi-Fi gap (insufficient evidence), then a cooling fault that moves the
batch to elevated and high risk before it recovers, with staff observations, inspection
notes and acknowledged alerts along the way.

```bash
cd backend
python -m scripts.seed_week --actor-user-id <operator> --vendor-user-id <vendor>
python -m scripts.live_feed --actor-user-id <operator>   # keeps the sensor reporting
```

Everything it writes stays marked simulated (device, readings and batch attributes), and
the UI shows that tag. It refuses to run twice for the same batch identifier and never
touches other batches. To remove the batch from the lists, archive it in the app.
Stopping `live_feed` is a real outage: the device goes stale and, with
`python -m app.monitor` running, the matching alert is raised.

### Devices, batches and history

A device is hardware and a batch is a period of monitoring, so they are linked by
assignments instead of being fixed together. Flash an ESP32 once with its
`DEVICE_ID` and token, then point it at whichever batch it serves:

- `POST /api/v1/devices/{id}/assignment` with `{"batch_id": ...}` assigns it. If it
  already serves another batch, the call returns 409 `device_assigned` unless the
  body also has `"replace": true`, so a device is never moved by accident.
- `DELETE /api/v1/devices/{id}/assignment` releases it. Archiving a batch releases
  its devices automatically.
- `GET /api/v1/devices/{id}/assignments` lists every batch the device has served.
- `GET /api/v1/devices?unassigned=true` lists free devices;
  `GET /api/v1/devices?batch_id=...` lists every device that has ever served a batch.

The server picks the batch for each reading from the device's current assignment.
Readings, assessments and observations are never rewritten when a device moves: each
reading stays in the batch it was recorded for, and assessments read the devices that
served the batch, including ones that have since moved on. A reading from an
unassigned device is stored with no batch and returns HTTP 201 with a `notice`; it is
never attached to a batch later. This matters because the firmware discards a reading
after any 4xx response.

`batch_id` in the reading payload is deprecated. Existing firmware that still sends
it keeps working: the value is ignored (with a `notice` if it differs from the
assignment) and the device's assignment decides the batch. Remove `BATCH_ID` from the
sketch when convenient.

### Pairing a new ESP32

Operators no longer copy device IDs and tokens by hand. On the Devices page choose
**Pair an ESP32**: the server creates the device and shows a one-time code such as
`ABCD-EFGH`. The code is valid for 15 minutes and works once. A device claims it with
`POST /api/v1/pairing/claim` (public, rate limited) and receives its credential.
Codes are stored only as HMAC hashes. `POST /api/v1/devices/{id}/pairing` issues a new
code for an existing device; the old credential keeps working until the new code is
claimed. Readings from a device that has not been paired are rejected.

Firmware support is not done yet: the sketch in `firmware/` still uses a fixed
`DEVICE_ID` and token and has no pairing portal. Until it does, register a device with
a credential on the Devices page and flash that. This has not been compiled or flashed.

### Ask your data (chat)

The **Ask your data** button opens a chat drawer for plain-language questions about the
batches the signed-in user may see (`POST /api/v1/chat`). The server builds a fixed,
user-scoped evidence pack; the model only phrases an answer from it and never chooses
queries or tools. Questions about safety, shelf life or selling get a fixed decline.
If AI is off or fails, the reply is a deterministic summary. It uses the existing
Gemini adapter (`GEMINI_API_KEY`); tune with `CHAT_RATE_LIMIT`,
`CHAT_RATE_WINDOW_SECONDS` and `CHAT_EVIDENCE_CHARS`.

### Public landing page

The home page is a static page in `frontend/public/site/` (source: `landing/`), opened
at `/site/index.html`. The React app redirects `/` there. After editing
`landing/index.html`, copy it into `frontend/public/site/` again.

New readings return HTTP 201; matching event retries return HTTP 200 and
`duplicate: true`; changed payloads under the same event ID return HTTP 409.
History includes source time, ingestion time, simulation and warm-up flags.
Registered real devices must submit `simulated: false`. Device JWTs and user
tokens cannot substitute for one another.

Query `/batches/{id}/readings`, `/batches/{id}/observations`,
`/batches/{id}/assessment`, `/priorities`, `/alerts` and `/batches/{id}/decisions`
under `/api/v1` to inspect the result. List endpoints return
`items`, `total`, `limit`, `offset` (maximum limit 200). Reading history accepts
timezone-aware `start` and `end`. See the [OpenAPI contract](docs/openapi.json)
for all request/response fields, filters and admin endpoints.

## Risk, priorities and alerts

The default policy is **illustrative**, scoped to `tomato`, and stored with every
assessment. It is not validated produce science or food-safety certification.
The default six-hour window requires per-device coverage, adequate sample count,
fresh readings and a clean-air baseline predating the readings. Warm-up readings
are excluded. Missing/stale/implausible data, baseline changes, unsupported
commodities and mixed real/simulated windows return `insufficient_data`.

Features include temperature/humidity statistics, deltas and slope per hour,
coverage and **relative uncalibrated gas response** per device. No gas-specific
concentration or days remaining are computed. The deterministic score uses
configurable temperature, humidity, relative gas level and trend weights, then
takes the maximum device score. Labels (`fresh`, `early_decay`, `spoiling`) are
operational indicators. Rising MQ-135 readings can reflect ripening and other
influences. All consequential handling decisions require human review.

Recovery uses a score margin and two distinct evidence confirmations by default;
repeating a request with identical evidence does not advance recovery. Worsening
and insufficient-data states apply immediately. Alerts deduplicate each unresolved
batch/trigger at the database level. Acknowledgement records a human response;
resolution follows a changed assessment state. The local notifier records
**`mocked`**, never externally delivered.

Priority score = weighted deterministic risk + retained-state floor when hysteresis
keeps a higher state + stale-data inspection bonus + insufficient-evidence bonus.
Factors are returned. Ties use identifier then UUID. Ranking is meaningful only
with two or more batches. Operators can record `priority_override` with a requested
rank and rationale; responses retain `computed_rank` and expose the override record.
Requested ranks sort before unoverridden batches at the same position; final ranks
remain unique and contiguous. An override with no rank clears the prior override.

Configure rules with the JSON environment variable `RISK_POLICY`, for example:

```dotenv
RISK_POLICY={"version":"tomato-short-demo-v1","window_seconds":3600,"min_samples":6}
```

Other settings and bounds are defined in [config.py](backend/app/core/config.py)
and [policy.py](backend/app/risk/policy.py). Record a new policy version when
changing thresholds. History and archived batches are retained; there are no
destructive delete endpoints. Observations have no update/delete endpoint;
corrections reference an earlier observation in the same batch.

## Optional AI and retrieval

Set `GEMINI_API_KEY` and choose `GEMINI_MODEL` and `GEMINI_EMBEDDING_MODEL`, then run:

```bash
python -m app.worker
```

`--once` processes at most one job. The official `google-genai` SDK performs
structured generation and 768-dimensional normalized embeddings. pgvector is
enabled only by migration `0004`. Production requires that extension; migration
failures are surfaced. No raw high-frequency readings are embedded. Evidence
contains deterministic episode summaries, append-only observations, past
assessments and administrator-imported guidance with a source URL/review note.
No guidance or claimed storage thresholds are fabricated as validated sources.

The workflow is fixed: `load_features → quality_gate → retrieve_evidence → explain
→ validate → fallback`. Quality/disabled paths terminate through fallback before
generation. Queries are parameterized and scoped to the authorized batch or
same-commodity public guidance. Retrieval has top-k and conservative serialized-byte
caps under the configured token budget. Embedding failures use structured retrieval.
The worker indexes a bounded recent set per job; small deployments use exact vector
search, and large-corpus indexing/approximate search can be added later.

Pydantic validates schema, status, citations and human-review requirements. Outputs
with unsupported safety, shelf-life or consequential claims are rejected. This is
a conservative guard, not proof that arbitrary model text is true. Valid explanations
live in `ai_explanation`; the original deterministic explanation, score and status
are retained. `ai_status` is `ok`, `disabled`, `failed` or `invalid_output`;
`ai_job_status` separately records queue progress. No-key and quality-gated paths
use `disabled`. AI failures do not interrupt ingestion or change risk state.

Jobs use leases, row locks, stale-worker fencing and bounded crash retries. Provider
calls have timeouts and one SDK attempt; failed/invalid jobs terminate rather than
retry forever. Model/prompt/workflow versions, evidence IDs and visits are audited.
LangGraph brings `langchain-core` transitively; application code imports no LangChain
APIs, autonomous agents or tools. The [Gemini structured-output documentation](https://ai.google.dev/gemini-api/docs/structured-output),
[embedding documentation](https://ai.google.dev/gemini-api/docs/embeddings) and
[LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
were consulted for these boundaries.

## Development checks

From `backend/` with the environment activated:

```bash
python -m pytest -q
python -m ruff format --check app tests alembic scripts ../simulator
python -m ruff check app tests alembic scripts ../simulator
python -m mypy app scripts
python -m scripts.export_openapi
```

Ordinary tests use isolated SQLite databases and stub the adapter's call boundaries;
they need neither Neon nor a real Gemini key. Migration tests exercise clean
upgrade/downgrade/re-upgrade and schema equivalence, and compile PostgreSQL/vector
DDL. PostgreSQL-specific execution and live provider checks are reported separately
in [validation notes](docs/BACKEND_VALIDATION.md). `requirements.lock` pins the
72-package Linux verification environment; `pyproject.toml` defines the project
and dependency groups. A fresh package installation requires network access.

See [the backend plan](docs/BACKEND_PLAN.md), [pilot runbook](docs/PILOT.md), and
[firmware contract](firmware/README.md). The physical ESP32 firmware is implemented;
the pilot still needs sensor conditioning and baseline work as described above.
Further work includes live provider verification, MQTT, real notification providers,
local languages and deployment hardening. No deployment or external notification
was performed.

## Live Neon and Gemini smoke test

Once `.env` has the real Neon URL and Gemini key, run from `backend/` with the
installed backend dependencies:

```bash
python -m scripts.live_smoke --output ../docs/LIVE_SMOKE_RESULT.json
```

Or let uv install/run the required environment from your normal terminal:

```bash
uv run --with-requirements requirements.lock python -m scripts.live_smoke \
  --output ../docs/LIVE_SMOKE_RESULT.json
```

The command performs real provider calls with synthetic context and checks Neon
connectivity, migrations/pgvector, login, sensor ingestion/retries, history,
deterministic risk, the AI job/workflow, real vector distance, retrieval, priorities,
alerts and audit. It creates a unique schema inside an outer transaction and rolls
back schema/data afterward. Existing public application data and migrations are
untouched. It does not run a production monitor or send external notifications.
Reports contain status categories/counts, never credentials or raw provider errors.
A nonzero exit code means a check failed; provider and connection checks remain
independent so a Neon failure does not hide a Gemini result.
