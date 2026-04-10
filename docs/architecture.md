# Architecture Overview

`sched-v2` is being structured around clear boundaries so scheduling logic can stay pure, persistence can remain replaceable, and future AI-assisted refinement can plug in without leaking into core domain code.

## Layers

### `domain`

Home for core business concepts, value objects, and domain-facing types. This layer should remain independent of transport, storage, and orchestration concerns.

### `engine`

Home for the pure scheduling engine. It should accept explicit inputs, return deterministic outputs, and avoid direct knowledge of APIs, databases, or AI providers.

### `services`

Home for application workflows that coordinate domain, engine, infra, and AI capabilities. Preview/apply/save/export/refine use cases belong here, while API and file-response concerns stay outside this layer.

### `infra`

Home for persistence-facing concerns such as repositories, storage adapters, and database models. This layer should translate between storage representations and the rest of the application.

### `ai`

Home for pluggable AI interfaces and adapter implementations. This keeps future natural-language refinement logic isolated from the engine and API layers.

### `api`

Home for thin transport adapters such as request/response schemas and route wiring. This layer should stay lightweight and delegate real work to services.

## Persistence Model Notes

### Relationships

- `Tenant` owns all worker, station, shift, configuration, workspace, version, and refine-request data.
- `Worker`, `Station`, and `ShiftDefinition` are tenant-scoped master records.
- `WorkerStationSkill` links a worker to each station they are qualified to cover.
- `LeaveRequest` stores approved date-based worker unavailability.
- `MonthlyWorkspace` is the mutable planning container for one tenant and one calendar month.
- `MonthlyAssignment` rows belong to a `MonthlyWorkspace`.
- `MonthlyPlanVersion` stores immutable saved snapshots of a monthly plan.
- `ConstraintConfig` stores one full constraint config per scope instead of many active fragments.
- `RefineRequest` stores one natural-language change request plus its parsed intent and preview result.

### Meanings

- Current workspace: the single mutable working state for a tenant/year/month. Intended semantics are one current workspace per tenant/month, with assignments attached to that workspace.
- Saved version snapshot: an immutable `MonthlyPlanVersion` record whose `snapshot_json` captures the plan state at save time for history, audit, or future restore flows.
- Constraint config: a full replacement configuration for a scope. `scope_type="default"` is the tenant baseline, while `scope_type="monthly"` targets a specific `year/month`.
- Refine request: a lightweight record of `request_text`, parsed intent, preview output, and status. It is intentionally not a full chat transcript.
- Engine compatibility: repositories should later translate persistence models into pure engine/domain dataclass contracts so the engine never depends on storage records directly.

## Intentional Deferrals

- No scheduling business logic yet
- No API implementation yet
- No migration framework yet
- No LangGraph flow yet
- No import workflow yet
- No API/file download export behavior yet
