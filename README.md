# sched-v2

`sched-v2` is a DB-first rewrite of a restaurant scheduling MVP. It models the
monthly workflow a manager actually uses: assemble persisted staffing inputs,
generate a candidate schedule, inspect warnings, make bounded refinements,
promote a candidate into the current workspace, then save or export the result.

This is intentionally more than CRUD. The hard part is keeping generated
candidates, mutable current state, immutable saved versions, and AI-assisted
requests separate enough that a reviewer can trust what changed and why.
Preview/apply/save/refine boundaries matter because only apply mutates the
current workspace, only save creates version history, and refine can only
produce a candidate preview.

## Reviewer Path

The fastest manual demo is the server-rendered monthly workspace:

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

`http://127.0.0.1:8000/v2/monthly-workspace?tenant_slug=demo-restaurant&month_scope=2026-04`

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

## Architecture

See [docs/architecture.md](docs/architecture.md) for the longer architecture
story. At a high level:

- `app.api` is the Django page/API layer. It parses requests, renders the
  monthly workspace, maps JSON schemas, and delegates.
- `app.services` owns application workflows: preview, apply, save, export,
  refine, explain, and shared monthly context assembly.
- `app.infra` owns Django models and repositories. The browser and API never
  become the source of truth for persisted schedule state.
- `app.engine` is the pure scheduling engine. It accepts explicit planning
  inputs and returns deterministic month results plus evaluation metadata.
- `MonthlyCandidatePreview` persists server-side candidate previews with IDs and
  input fingerprints so apply can re-load a fresh candidate by scope.
- `app.ai` and the LangGraph refine/explain workflows keep model calls bounded
  and replaceable.
- `app.evals` plus `scripts/eval_refine_intents.py` provide an offline refine
  intent regression harness.

## Trust Boundaries

Important guarantees for review:

- Apply rejects assignment dates outside the selected month before mutating the
  current workspace.
- The browser is not trusted as the schedule source of truth.
- Preview/refine create server-side candidate IDs; apply re-loads the candidate
  for the selected tenant/month.
- Candidate input fingerprints reject stale candidates after relevant persisted
  inputs change.
- JSON API apply requires `candidate_id` and rejects arbitrary full result
  payloads.
- Model output cannot apply, save, or directly mutate schedules.
- Unsupported scheduling intent returns a safe non-executable outcome instead
  of guessing.

## AI Behavior

Refine uses scheduling-only structured intent parsing. Supported executable
requests are currently narrow single-day assignment edits/removals that produce
a candidate preview. Abstract but scheduling-related requests, such as workload
fairness or broad station coverage changes, are understood but not executable.
Non-scheduling requests are rejected.

Explain is bounded to one selected day and the loaded schedule context. It can
compare current workspace facts with a candidate preview, but it remains
read-only.

Environment variables for real model calls:

- `OPENAI_API_KEY`
- `OPENAI_REFINE_MODEL`
- `OPENAI_EXPLAIN_MODEL`

Compatibility aliases also exist in code for local experimentation, but tests
and evals do not require real API keys and use fake/noop clients.

## Offline Eval

Run:

```bash
python scripts/eval_refine_intents.py
```

The eval runs a fixed zh/ja/en corpus through the deterministic local refine
parser path with a noop model client. It checks expected domain,
capability status, intent type, missing-field handling, and whether a candidate
preview should be created.

This is offline-safe and is not a real-model benchmark. Treat it as a
reviewer-facing regression artifact: a passing executable row means a candidate
preview was created, while a passing non-executable row means the request was
safely classified without creating a preview. Failures identify which table
column diverged, and the summary reports pass/fail counts by category and
language.

## Intentional Limitations

- Local/demo-oriented deployment.
- No production auth, RBAC, or tenant access-control story yet.
- No full optimizer for fairness or workload balancing.
- No candidate cleanup or retention policy yet.
- Saved versions exist, but there is no full restore/versioning UI yet.
- SQLite/localdev assumptions in the default manual-review path.
- AI behavior is bounded and conservative rather than a broad scheduling agent.

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
