# Seeded AI demo — 2026-10-13

## Implemented

`POST /api/v1/demo/batches` and the Batches **Seed demo batch** button create a new,
user-owned, labelled synthetic tomato batch. Admin/operator authentication is
required; vendors and anonymous callers are denied. Device creation is restricted
to an internally generated simulated device; real device provisioning remains
administrator-only. No credentials are returned from the demo endpoint.

The default policy receives 73 seed-42 readings across six hours, a baseline recorded
before all readings, two synthetic observations, a deterministic assessment and
its normal evidence/alert/audit records. Other tomato windows use their configured
sampling cadence. Quality failure rolls the transaction back. An unsupported
commodity policy is rejected. Existing records are not deleted or overwritten.

`scripts.seed_demo --explain` creates a persistent example and processes only its
own explanation job. `--batch-id` appends a new assessment to an existing demo.
Worker claim filtering preserves the ordinary queue path and lease fencing.

## Verification

- Backend full suite: **67 tests passed** (`.venv/bin/python -m pytest -q`).
- Frontend component suite: **18 passed** (`npm run test`).
- New desktop/mobile browser journeys: **2 passed**
  (`npm run test:e2e -- --grep 'operator seeds'`).
- `npm run build`, `npm run format:check`, Ruff and mypy passed.
- Tests cover a complete data window, baseline chronology, simulation labels,
  observations, quality rollback, authorization, distinct repeat seeds, disabled
  AI, validated adapter output, and selected-job processing without draining
  another pending assessment. Tests stub only the existing adapter boundaries.

## Live seed

Created **DEMO-TOMATO-937a733a** in the configured database under the existing
administrator account. Batch ID: `c5442bf0-743e-4701-b0c8-4c22efa54228`.
It contains 73 simulated readings, one baseline and two synthetic observations.
The first deterministic assessment has a score and the operational `spoiling`
indicator (shown as High risk in the UI). This is a pipeline scenario, not a
finding about real produce.

The first actual Gemini response was rejected as `invalid_output`, with failed AI
job status and no accepted explanation. A diagnostic invocation on only this
synthetic evidence produced a valid, complete explanation with permitted evidence
citations. A new assessment was requested to retain the initial failure in history.
See the final task report for the persisted latest AI status.

Further diagnosis identified truncated JSON (`EOF while parsing a string`), rather
than a reason to loosen the schema or evidence guard. The Gemini 2.5 Flash adapter
now requests 512 thinking tokens and a 3,000-token total output budget, with concise
field instructions. The strict validator is unchanged. Prompt protocol version
`explanation-v2` is recorded on new assessments and actual worker execution. The
real-SDK mock-transport test checks that both budgets reach the request payload.
The full 67-test regression suite passes after this fix.

Final live verification created **DEMO-TOMATO-da554107** with a fresh window
(batch ID `6223075f-d2a5-49ca-a561-c31cdbfc5331`). Its persisted assessment
`6bbd8b13-0fa9-4e01-84e5-9f676a0f76e1` has `ai_status: ok`,
`ai_job_status: done`, an accepted real Gemini explanation and **three evidence
citations**. It contains 73 simulated readings, one baseline and two observations.
The earlier demo and failed assessments remain available as history. Open the
fresh batch's Assessment tab for the verified output.

Live checks used the configured Neon/Gemini services with approved network access.
No credential or provider response was written to this report. No real-device
data or external notifications were generated. Seeded data ages normally; use a
new demo after its latest source timestamps become stale.
