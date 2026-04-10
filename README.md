# sched-v2

DB-first rewrite of a restaurant scheduling MVP with a pure scheduling engine and a thin API boundary.

## Current Scope

This bootstrap step creates the initial Python project skeleton, basic package layout, and lightweight architecture documentation only.

## Architecture Direction

- `domain`: core business concepts and future domain entities
- `engine`: pure scheduling contracts, validators, and orchestration entry points
- `services`: application-level workflows such as preview, apply, save, export, and refine
- `infra`: persistence-facing models and repository abstractions
- `ai`: pluggable AI interfaces and future natural-language refinement integration
- `api`: thin transport layer for schemas and routes

Business rules, API behavior, database migrations, scheduling logic, and LangGraph flows are intentionally deferred.
