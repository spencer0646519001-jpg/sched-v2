# sched-v2

DB-first rewrite of a restaurant scheduling MVP with a pure scheduling engine, a thin API boundary, and a Django-first runtime direction.

## Current Scope

The current scaffold includes persistence models, repository and service boundaries, API schemas, framework-neutral route translation, and a thin Django-first runtime adapter skeleton.

## Architecture Direction

- `domain`: core business concepts and future domain entities
- `engine`: pure scheduling contracts, validators, and orchestration entry points
- `services`: application-level workflows such as preview, apply, save, export, and refine
- `infra`: persistence-facing models and repository abstractions
- `ai`: pluggable AI interfaces and future natural-language refinement integration
- `api`: thin transport layer for schemas, framework-neutral route translation, and Django-first runtime adapters

Business rules, repository-backed runtime wiring, database migrations, scheduling logic, and LangGraph flows are intentionally deferred.
