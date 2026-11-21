# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React, TypeScript and Vite, specified by prd.md and prompt.md. Existing FastAPI backend.

## Users

Warehouse operators monitor produce, inspect risk evidence and record observations, often on a phone. Administrators provision devices and users. Vendors have read-only access to their own batches.

## Product Purpose

Turn timestamped environmental readings into transparent operational risk indicators and a traceable human inspection workflow. The user confirmed equal emphasis on inspection/data quality, live readings, and batch/device setup.

## Operating Context

Tomato-carton pilot with ESP32, DHT22 and MQ-135; a seeded simulator exercises the same ingestion API. A device baseline precedes the monitoring window. Operators record starting conditions, routine observations and final outcomes.

## Capabilities and Constraints

Batch create/update/archive; device provisioning and baselines; sensor history; deterministic assessments with optional validated AI explanations; priorities, alerts, decisions and audit. Authentication uses expiring JWTs and backend-enforced roles. Access tokens stay in memory; a reload requires login. Observations are append-only.

User-authorized scope update: self-signup supports operator and vendor roles, defaults to vendor, and forbids administrator registration. Operators share warehouse access; vendors see only assigned batches. Public operator signup is for a trusted demo and must be restricted before a real deployment.

Operators/admins can explicitly seed a separate, labelled synthetic tomato batch for AI testing. Demo readings pass through the existing ingestion validation with an ephemeral simulated-device credential. Seeding records a baseline, synthetic observations and an assessment; the real explanation worker handles AI. Existing history remains intact and vendors remain read-only.

## Evidence on Hand

prd.md, agent.md, prompt.md and docs/openapi.json are the specification and API contract. No customer testimonials, impact claims, validated prediction accuracy or shelf-life estimates are available.

## Product Principles

Expose evidence and uncertainty. Distinguish simulation from hardware. Preserve historical records. Require human review for consequential handling. Keep monitoring useful when AI is disabled.

## Accessibility & Inclusion

Phone-friendly layouts, keyboard controls, labelled forms, readable text and explicit status labels independent of color. Reduced motion support; sensor and observation strings rendered as text.

## Open Decisions

Harvest is a provisional interface name, not a claimed existing brand. Hosting, physical hardware validation and external notification delivery remain separate milestones.

User-authorized scope update: devices are decoupled from batches through assignments, operators pair ESP32 devices with one-time codes, and an "Ask your data" chat answers questions from a fixed, user-scoped evidence pack through the existing AI adapter. Because open signup can create operators, any operator can now register devices and rotate their credentials: restrict operator signup before a real deployment.
