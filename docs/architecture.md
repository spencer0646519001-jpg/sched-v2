# Architecture Overview

`sched-v2` keeps scheduling logic, persistence, transport, and AI behavior in
separate layers. The project is a restaurant monthly scheduling slice, so the
important architectural story is state movement: persisted inputs produce a
candidate preview; a fresh candidate can be applied into the mutable current
workspace; the current workspace can be saved as an immutable version.

## Layers

### `app.api`

The API/page layer is Django-first. `django_workspace.py` renders the
reviewer-visible monthly workspace page, `django_views.py` adapts JSON requests
to schema objects, and `routes.py` keeps framework-neutral request/response
translation for preview, apply, save, refine, explain, and export.

This layer should stay thin: parse, validate, render, and delegate.

The runtime starts through `manage.py`. Local review uses
`app.localdev_settings`; rented-server demo deployment uses
`app.deploy_settings` with environment variables and the same URLConf. The
initial rented-server rollout is side-by-side with sched-mvp v1, using a
separate v2 checkout, environment file, SQLite volume, Compose project name,
and host port.

### `app.services`

Services coordinate use cases across repositories, engine contracts, and AI
workflows:

- `preview` loads monthly context and returns a read-only candidate result.
- `apply` promotes a candidate result into the mutable current workspace.
- `save` writes immutable monthly plan versions.
- `export` reads current workspace state and builds export rows/CSV.
- `refine` stores a refine request and returns an optional candidate preview.
- `explain` loads one day of schedule context and returns a read-only
  explanation.
- `monthly_context` centralizes monthly data assembly for preview/refine/explain.

Services are framework-neutral and should not know about Django requests.

### `app.infra`

The infra layer owns persistence-facing records, Django ORM models, and
repository adapters. Repositories translate between tenant-scoped database rows
and service/engine-facing contracts.

Important persistence concepts:

- `Tenant` scopes all data.
- `Worker`, `Station`, `ShiftDefinition`, and `WorkerStationSkill` are master
  scheduling inputs.
- `LeaveRequest` and `ConstraintConfig` add month-specific constraints.
- `MonthlyWorkspace` is the mutable current state for one tenant/month.
- `MonthlyAssignment` rows belong to a workspace.
- `MonthlyPlanVersion` stores immutable saved snapshots.
- `MonthlyCandidatePreview` stores server-side preview artifacts with input
  fingerprints.
- `RefineRequest` stores one request, parsed intent, and optional preview result.

Demo tenant setup is handled by `seed_monthly_workspace_demo`, which creates
the `demo_kitchen` tenant plus workers, stations, shifts, worker station skills,
worker scheduling profile JSON, and default constraint config. New restaurant
setup is still internal-only through seed scripts, fixtures, or private data
management; production self-serve onboarding is not part of this architecture
yet. See [Tenant Data And Admin Boundaries](tenant-data.md).

### `app.engine`

The engine is pure scheduling code. It accepts explicit `MonthPlanningInput`
contracts and returns deterministic `MonthPlanningResult` data with warnings,
summary information, and a reviewer-facing evaluation envelope. It does not
depend on Django, the database, HTTP, or model providers.

The current engine is intentionally simple. It is deterministic and
reviewable, not a full optimizer for fairness or workload balancing.

### Candidate Preview Persistence

Preview and refine return candidates that are not immediately trusted back from
the browser. The runtime persists candidate results server-side and returns a
candidate ID. Apply then re-loads that ID for the selected tenant/month and
checks freshness before mutating current workspace state.

Freshness is based on a fingerprint of persisted inputs that matter to applying
the candidate: tenant/month scope, worker/station/shift data, station skills,
leave requests, resolved constraints, and current workspace state.

### AI, Refine, And Explain

`app.ai` defines replaceable model interfaces and noop clients. Real OpenAI
clients are built from environment variables only when configured.

`refine_langgraph.py` performs scheduling-only structured intent parsing. It
allows narrow executable single-day edits/removals to create candidate previews,
classifies broader scheduling asks as understood but not executable, and rejects
non-scheduling or direct apply/save-style requests.

`explain_langgraph.py` is bounded to selected-day schedule context. It can use a
model to shape a day explanation, but the service remains read-only and falls
back safely when no model is available.

### Offline Eval Harness

`app.evals.refine_intent_eval` and `scripts/eval_refine_intents.py` run a fixed
offline corpus against the deterministic refine parser path with a noop model
client. The harness checks domain classification, capability status, intent
type, missing-field handling, and preview creation expectations.

The eval is a regression artifact for reviewers, not a real-model benchmark.

## Trust And Safety Boundaries

- Apply validates that all candidate assignments stay inside the target month
  before writing.
- Apply validates worker, station, and shift identifiers against tenant-scoped
  repository data.
- JSON API apply accepts `candidate_id` only and rejects full result payloads.
- Server-rendered workspace apply uses server-side candidate IDs rather than
  trusting hidden form schedule payloads.
- Candidate freshness prevents applying stale previews after relevant persisted
  inputs change.
- Refine may produce a candidate preview, but never applies or saves it.
- Explain is read-only and scoped to one selected day.
- Unsupported scheduling requests produce safe non-executable outcomes.
- Non-scheduling requests are rejected by the bounded AI workflows.
- Django admin registrations are internal-only operator scaffolding and are not
  mounted by the shipped local/demo settings.

## Current Deferrals

- No production auth/RBAC layer.
- No public tenant onboarding or production tenant-management UI.
- No broad autonomous agent loop.
- No full optimizer for fairness/workload balancing.
- No candidate preview cleanup/retention policy.
- No full saved-version restore UI.
- No production SaaS hardening beyond the Docker Compose/SQLite demo path.
