# CLAUDE.md
## Project Context (Important)

This is a **portfolio project** for the developer's career transition
from Michelin-starred pastry chef (10 years) to Applied AI Engineer.

Target roles: AI Applied Engineer at companies like Preferred Networks,
Telexistence (Tokyo), or Delta Electronics (Taipei).

Background: This is `sched-v2` — a clean rewrite of an earlier MVP,
built with AI-assisted development (Codex 5.5).

When reviewing this codebase, prioritize:
1. What signals does this code send to a hiring manager?
2. Is the AI engineering work (prompts, evals, observability) credible?
3. Does the README + architecture tell a strong story?

The developer is also building a second project: a LINE webhook
"night gatekeeper" for his mother's guesthouse (real users, real problem).


This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable with dev extras)
python -m pip install -e ".[dev]"

# Database setup and demo seed
python manage.py migrate
python manage.py seed_monthly_workspace_demo

# Run local server
python manage.py runserver
# → http://127.0.0.1:8000/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04

# Lint
python -m ruff check .

# Full test suite
python -m pytest -q

# Single test file
python -m pytest tests/test_engine_monthly.py -q

# Offline eval harness (no API key required)
python scripts/eval_refine_intents.py
```

Tests configure Django in-memory SQLite automatically via `tests/conftest.py` — no extra env setup needed. `OPENAI_API_KEY` is stripped in tests to prevent live model calls.

### Private admin (local only)

```powershell
$env:DJANGO_SETTINGS_MODULE = "app.admin_local_settings"
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8002
# → http://127.0.0.1:8002/admin/
```

Run on port 8002 to avoid colliding with the default local server on 8000. Admin is not mounted by `localdev_settings` or `deploy_settings`.

### Docker demo deployment

```bash
docker compose -p sched-v2 build
docker compose -p sched-v2 run --rm web python manage.py migrate
docker compose -p sched-v2 run --rm web python manage.py seed_monthly_workspace_demo
docker compose -p sched-v2 up -d
```

Required env vars: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `ALLOWED_HOSTS`, `OPENAI_API_KEY`, `OPENAI_REFINE_MODEL`, `OPENAI_EXPLAIN_MODEL`. Use `SCHED_V2_PORT=8001` for side-by-side with v1 (v1 occupies host port 8000; v2 maps to 8001). Caddy provides HTTPS for the public demo at `sched.spencerailab.com`.

## Architecture

### Layer Map

```
app.api        → Django transport/page layer; should delegate and avoid new business logic
app.services   → use-case orchestration; framework-neutral
app.infra      → Django ORM models + repository adapters
app.engine     → pure, deterministic scheduling logic (no Django, no DB, no AI)
app.ai         → replaceable model interfaces + noop/OpenAI clients
app.evals      → offline refine intent regression corpus
```

### Key Data Flow

1. **Preview/Refine**: `app.services.monthly_context` assembles `MonthlyPlanningPersistenceBundle` from repositories → translates into `MonthPlanningInput` → passes to `app.engine.monthly` → returns `MonthPlanningResult` → persisted server-side as `MonthlyCandidatePreview` with an ID and input fingerprint.

2. **Apply**: The public JSON API (`routes.py`) accepts `candidate_id` only and rejects full result payloads — re-loads the candidate from the server, checks freshness via input fingerprint → `app.services.apply` writes assignments into `MonthlyWorkspace`. Internal service paths may accept typed structural results directly.

3. **Save**: Snapshots current workspace into immutable `MonthlyPlanVersion`.

### Engine Contracts (`app/engine/contracts.py`)

The engine boundary is strictly typed dataclasses. The main types:
- **In**: `MonthPlanningInput` → workers, stations, shifts, leave requests, constraint config, optional `AssignmentPatchInput` list (refine layer)
- **Out**: `MonthPlanningResult` → assignments, warnings, `MonthPlanningSummary`, `MonthPlanningEvaluation`, metadata

Nothing outside `app.engine` should compute schedules. Nothing inside `app.engine` should touch Django, the DB, or model providers.

### Infra Persistence Concepts

- `Tenant` scopes everything.
- `MonthlyWorkspace` is the single mutable current state per tenant/month.
- `MonthlyCandidatePreview` stores server-side preview artifacts — apply re-loads these by `candidate_id`, never trusts the browser as schedule source.
- `RefineRequest` stores the raw request text, parsed intent JSON, and optional preview result.
- `MonthlyPlanVersion` is immutable (saved history).

### AI Layer

`app.ai.interfaces` defines two `Protocol` interfaces: `StructuredOutputModelClient` (JSON generation) and `AudioTranscriptionClient`. `app.ai.noop_client` provides deterministic fallbacks used in tests and evals. Real OpenAI clients are built only when `OPENAI_API_KEY` is set.

`app.services.refine_langgraph` uses `LangGraphRefineWorkflow` to parse free-form text into structured `AssignmentPatchInput`s. Supported: narrow single-day assignment edits/removals. Broader scheduling asks are classified as understood but non-executable. Non-scheduling requests are rejected. **Refine never mutates the workspace directly.**

### Trust Boundaries to Preserve

- Apply rejects assignment dates outside the selected month before any write.
- API apply validates `candidate_id` exists, belongs to the correct tenant/month, and passes the input fingerprint freshness check.
- Candidate input fingerprint covers: tenant/month scope, worker/station/shift data, station skills, leave requests, resolved constraints, and current workspace state.
- Model output cannot apply, save, or directly mutate anything.

### Settings Profiles

| File | Use |
|---|---|
| `app/localdev_settings.py` | Default local dev, SQLite, no admin |
| `app/admin_local_settings.py` | Local with Django admin mounted |
| `app/deploy_settings.py` | Docker demo deployment via env vars |

`manage.py` defaults to `app.localdev_settings`.

### URL Layout

| Path | Purpose |
|---|---|
| `/v2/monthly-workspace` | Server-rendered monthly workspace page |
| `/v2/monthly-workspace/export.csv` | CSV export download |
| `/v2/monthly-schedules/preview` | JSON API — generate candidate |
| `/v2/monthly-schedules/apply` | JSON API — apply candidate by ID |
| `/v2/monthly-schedules/save` | JSON API — save version snapshot |
| `/v2/monthly-schedules/refine` | JSON API — AI-assisted refine |
| `/v2/monthly-schedules/explain-day` | JSON API — day explanation |
| `/v2/monthly-schedules/export` | JSON API — export rows |

Routes are registered by `app.api.django_urls` consuming the framework-neutral `MonthlyScheduleRoutes` bundle from `app.api.routes`.
