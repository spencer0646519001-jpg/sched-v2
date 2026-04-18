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

## Local Manual Review

The repo includes a tiny local Django bootstrap path for manually reviewing the
server-rendered monthly workspace page without widening into a fuller runtime
rewrite.

1. Create the local SQLite database and apply migrations:
   `.\.venv\Scripts\python manage.py migrate --noinput`
2. Seed a small demo tenant:
   `.\.venv\Scripts\python manage.py seed_monthly_workspace_demo`
3. Start the local server:
   `.\.venv\Scripts\python manage.py runserver`
4. Open:
   `http://127.0.0.1:8000/v2/monthly-workspace?tenant_slug=demo-restaurant&month_scope=2026-04`
