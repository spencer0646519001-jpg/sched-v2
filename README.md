# sched-v2

For ten years I worked the pastry side of Michelin kitchens — eight at a
two-star in Taipei, two at a three-star in Tokyo. Building the monthly staff
schedule was part of the job, every month, for a decade. That repetition taught
me something specific about scheduling tools: a perfectly-optimized schedule is
the wrong shape of answer. The hardest part of a monthly schedule isn't the
first 80 percent an optimizer can compute — it's the last 20 percent that only
a manager who knows the people can resolve. `sched-v2` is the codebase that
takes that judgment seriously: a Django service whose deterministic engine
deliberately stops at a usable 80-percent draft, surfaces what's still wrong
through warnings, and hands the rest to the manager through a bounded
natural-language refine loop.

## Why this exists — the 80-point hypothesis

The conventional answer to staff scheduling is a 100-point optimizer: the
cleanest possible schedule given hard constraints and a fairness objective.
After ten years of building monthly schedules in Michelin kitchens, I think
it's the wrong shape of answer. The hard part isn't the first 80 percent — it's
the last 20 percent only a manager who knows the people can resolve: who's
covering for someone away on a stage, which two stations pace each other on a
busy night, which new hire is in the second week of their ramp-up. Pulling a
fully-optimized schedule apart to make room for those things is slower than
building forward from a strong starting point. So sched-v2 inverts the goal:
the engine produces an explainable 80-percent draft plus complete warnings
(under-staffed days, missing skills, leave conflicts), and the manager finishes
it with natural-language edits. I might be wrong about this for other domains;
for restaurant scheduling, it's the shape of the problem I keep seeing.

The four parts of the system map to the temporal order a manager actually uses
them: read the draft and warnings, talk to the system in natural language to
fix the obvious things, open a per-day explanation when one assignment looks
wrong, and export CSV when it's ready to hand to the floor.

## v1 → v2: what I learned

v1 was the version I built while learning Django for the first time. When
engineering friends reviewed it, the feedback was specific: the engine imported
Django models, called OpenAI inside scheduling logic, and the only path to test
scheduling correctness was a full Django test client. The verdict was polite
but plain — "this works, but you can't review it." Before starting v2, I spent
a week reading hexagonal architecture and ports-and-adapters, plus how mature
Django codebases handle app boundaries, then paired with Codex 5.5 to do the
rewrite.

## How v2 was built

Four architectural constraints were settled before any v2 code was written:

- **The engine is pure.** No Django imports, no DB calls, no model calls.
- **The API layer stays thin.** Parse requests, delegate to services, render.
- **Tenant-aware everywhere.** Multi-tenant from day one, not retrofitted.
- **Services own workflow orchestration.** Engine and infra never call each
  other through the API.

Inside those four boundaries, I paired with Codex 5.5 on the implementation.
The decisions are mine; the implementation velocity is the AI's.

## AI-assisted development disclosure

This is what AI-assisted development looks like when architectural boundaries,
product judgments, and deployment decisions stay with me, not the model. Three
examples from this build:

- **Layout.** The initial cut put the schedule grid front and center. I moved
  it below the controls, evaluation summary, warnings, and refine panel — a
  manager opening the page mid-month needs to see what's wrong with the
  current draft before they see the draft itself.
- **Refine semantics.** The first refine parser required date, worker, shift,
  and station on every request. I rewrote it to accept partial edits:
  `Spencer, swap to C-shift on 5/2` shouldn't have to specify the station —
  that's not how corrections are phrased mid-shift. The parser also refuses,
  rather than guesses, when a request is genuinely ambiguous.
- **Capability boundary.** An early draft of refine collapsed every input into
  `parseable` or `rejected`. I split it into four states — executable,
  understood-but-not-executable, ambiguous-or-missing, and non-scheduling — so
  a request like `make this month fairer across staff` is recognized as
  scheduling intent the system understands but cannot safely execute, rather
  than getting force-parsed into a narrow assignment edit.

A longer version with seven examples (three product/domain, four
deployment/portfolio) is in
[docs/case-study-v1-to-v2.md](docs/case-study-v1-to-v2.md).

## Live Demo

sched-v2 is the main live demo, hosted on a rented DigitalOcean server behind
Caddy HTTPS. Admin is intentionally disabled in deploy settings.

Primary demo:

`https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=zh`

Japanese UI:

`https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=ja`

v2 is currently in a stabilization window. The earlier sched-mvp (v1) remains
reachable on the same server on host port `8000` as a side-by-side reference.
Once v2 clears that window, v1 will be retired from public access and kept
only as a GitHub reference. See
[docs/case-study-v1-to-v2.md](docs/case-study-v1-to-v2.md) for the rewrite
case study.

## Reviewer Path

The fastest manual demo is the server-rendered monthly workspace, which
surfaces the 80-percent draft → refine → apply → save flow in clickable form:

1. Select the tenant/month.
2. Generate a preview.
3. Inspect the evaluation summary, warnings, and human-readable notices.
4. Refine the current workspace with a natural-language scheduling request.
5. Review the returned candidate preview.
6. Apply the candidate into the current workspace.
7. Save a version or export CSV.
8. Explain one day in the schedule.

Fresh seeded data starts without a current workspace. If refine says a current
workspace is required, apply the first generated preview once to establish the
baseline, then run the refine/review/apply part of the flow.

Seeded local URL:

`http://127.0.0.1:8000/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04`

Model-backed refine and explain are optional. Without model environment
variables, the app uses noop/fallback clients so local review, tests, and the
offline eval remain safe and do not call the OpenAI API.

## Local Setup

```bash
python -m pip install -e ".[dev]"
python manage.py migrate
python manage.py seed_monthly_workspace_demo
python manage.py runserver
```

Quality checks:

```bash
python -m ruff check .
python -m pytest -q
python scripts/eval_refine_intents.py
```

The local Django settings use SQLite at `localdev.sqlite3`.

### Private Local Admin

For local tenant/demo data sanity checks, use the private admin settings
profile. This reuses `localdev.sqlite3`, installs the standard Django admin
stack, and mounts `/admin/` only for that settings module:

```bat
set DJANGO_SETTINGS_MODULE=app.admin_local_settings
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/`. The normal local and demo deployment
settings leave admin disabled.

## Tenant Data

The demo tenant/data story is documented in
[docs/tenant-data.md](docs/tenant-data.md). In short, the demo uses
`python manage.py seed_monthly_workspace_demo`, which seeds the `demo_kitchen`
tenant with workers, stations, shifts, worker station skills, scheduling
profile JSON, and the default constraint config used by the DB-backed monthly
workspace.

New restaurant setup is currently internal: seed scripts, fixtures, or a
private data-management process. Production self-serve onboarding is not built
yet. Minimal Django admin registrations exist for core scheduling data, but the
shipped local/demo settings do not mount admin; it is internal-only and not
part of the public reviewer demo surface.

## Demo Deployment

See [docs/deployment.md](docs/deployment.md) for the repeatable rented-server
demo path. The current deployment is side-by-side with sched-mvp v1 on a
rented DigitalOcean server: v1 remains in `/root/sched-mvp` on host port
`8000`, while v2 runs separately from `/root/sched-v2` on host port `8001`
using its own `.env`, SQLite volume, and Compose project name. Caddy provides
HTTPS for the public v2 demo domain.

```bash
docker compose -p sched-v2 build
docker compose -p sched-v2 run --rm web python manage.py migrate
docker compose -p sched-v2 run --rm web python manage.py seed_monthly_workspace_demo
docker compose -p sched-v2 up -d
```

The container starts Django with:

```bash
python manage.py runserver 0.0.0.0:8000 --noreload
```

Required demo server environment variables:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `ALLOWED_HOSTS`
- `OPENAI_API_KEY`
- `OPENAI_REFINE_MODEL`
- `OPENAI_EXPLAIN_MODEL`

For side-by-side deployment, set `SCHED_V2_PORT=8001`. Host port `8001` maps to
the container's internal port `8000`, avoiding the v1 host-port `8000`
collision. The seeded v2 demo URL is:

`https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=zh`

The Compose service stores the SQLite database at `/data/sched-v2.sqlite3` in
the project-scoped volume `sched_v2_sqlite`, so rebuilds and restarts do not
reset the demo database. This is intentionally a portfolio/demo deployment
path, not a production SaaS hardening pass.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the longer story. The
repo is layered:

- `app.engine` — pure, deterministic scheduling logic. No Django, no DB, no
  model calls.
- `app.services` — workflow orchestration: preview, apply, save, export,
  refine, explain, monthly context assembly.
- `app.infra` — Django models and repository adapters.
- `app.api` — thin HTTP/render layer that delegates to services.
- `app.ai` plus the LangGraph refine/explain workflows — bounded, replaceable
  model layer.
- `app.evals` plus `scripts/eval_refine_intents.py` — offline refine intent
  regression harness.

`MonthlyCandidatePreview` persists candidate previews server-side with input
fingerprints, so apply re-loads a fresh candidate by ID rather than trusting
browser-submitted schedule payloads.

## Trust Boundaries

The four guarantees most worth verifying:

- **Server is the source of truth.** Apply re-loads candidates by `candidate_id`
  for the selected tenant/month; the browser cannot submit a full schedule
  payload.
- **Candidate freshness.** Input fingerprints reject stale candidates after
  relevant persisted inputs change.
- **Off-month writes blocked.** Apply rejects assignments outside the selected
  month before any DB write.
- **Model output cannot mutate.** Refine produces candidate previews only;
  refine, explain, and the model layer never reach apply or save.

Unsupported scheduling intent returns a safe non-executable outcome rather
than guessing.

## AI Behavior

The refine workflow is human-in-the-loop and bounded:

1. The user enters a free-form scheduling instruction.
2. `LangGraphRefineWorkflow` parses it into structured intent (deterministic
   fallback if no API key is set).
3. The server generates a non-mutating candidate preview and a before/after
   `preview_diff`.
4. The UI renders a Proposed-changes block; the user explicitly applies before
   any state changes.

Supported executable refines are narrow single-day assignment edits or
removals. Abstract scheduling-related requests (workload fairness, broad
station coverage changes) are classified as understood-but-not-executable.
Non-scheduling requests are rejected. Explain is read-only and bounded to one
selected day plus its loaded schedule context.

Environment variables for live model calls: `OPENAI_API_KEY`,
`OPENAI_REFINE_MODEL`, `OPENAI_EXPLAIN_MODEL`. Tests and the offline eval do
not require API keys and use deterministic noop clients.

## Offline Eval

```bash
python scripts/eval_refine_intents.py
```

The eval runs a fixed zh/ja/en corpus through the deterministic local refine
parser path with a noop model client. It checks expected domain, capability
status, intent type, missing-field handling, and whether a candidate preview
should be created.

This is offline-safe and not a real-model benchmark — it is regression
coverage for the deterministic parser path. A passing executable row means a
candidate preview was created; a passing non-executable row means the request
was safely classified without creating a preview. Live-model evaluation is on
the next-iteration list (see *Honest Trade-offs*).

## Honest Trade-offs

- Local/demo-oriented deployment, not production SaaS hardening.
- No production auth, RBAC, or tenant access-control story yet.
- No production self-serve restaurant onboarding UI.
- SQLite-backed demo deployment, not a production database architecture.
- No candidate cleanup or retention policy.
- Saved versions exist; there is no full restore/versioning UI yet.
- No observability layer, and the offline eval is regression coverage rather
  than a live-model benchmark — both are next iteration before live job
  applications.

## Reviewer Checklist

What to inspect:

- Pure engine boundary in `app.engine`.
- Shared monthly context assembly in `app.services.monthly_context`.
- Apply/candidate trust boundary in `app.api.routes`,
  `app.api.django_workspace`, and `app.infra.django_repositories`.
- AI refine/explain safety in `app.services.refine_langgraph` and
  `app.services.explain_langgraph`.
- Offline eval harness in `app.evals.refine_intent_eval` and
  `scripts/eval_refine_intents.py`.
- Tests under `tests/`, especially monthly schedule integration, workspace UI,
  refine/explain, and reviewer story coverage.
- Monthly workspace UI at `/v2/monthly-workspace`.
