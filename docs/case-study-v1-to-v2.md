# Case Study: sched-mvp v1 to sched-v2

## Summary

sched-mvp v1 validated the core restaurant scheduling MVP workflow: a manager
could load a demo month, inspect generated assignments, and see that a
schedule-oriented product concept was worth continuing. It proved the workflow,
but it was not the right long-term architecture for a reviewer-facing system
where generated candidates, saved schedules, AI requests, and user actions need
clear trust boundaries.

`sched-v2` is the DB-first rewrite. The rewrite focuses on backend trust,
explicit state transitions, and applied AI boundaries. The goal is not to make
the model a broad scheduling agent; the goal is to let AI help with narrow,
reviewable scheduling requests while the server remains the source of truth for
what can be applied, saved, exported, or explained.

## Positioning

v2 is the main live demo. It is hosted on a rented DigitalOcean server behind
Caddy HTTPS:

`https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=zh`

Japanese UI:

`https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=ja`

v1 remains on the same server on host port `8000` as a legacy/reference project.
It is useful for explaining the rewrite journey, but it should not be presented
as an equal main live demo. The reviewer-facing story should lead with v2 and
use v1 as context for why the rewrite matters.

## What Changed

### Backend Boundaries

v2 separates the system into service, repository, and engine boundaries:

- `app.engine` owns deterministic scheduling logic.
- `app.infra` owns Django models and repository persistence.
- `app.services` owns workflows such as preview, apply, save, export, refine,
  explain, and monthly context assembly.
- `app.api` parses HTTP requests, renders the monthly workspace, maps JSON
  schemas, and delegates to services.

This keeps the browser and AI workflows from becoming the source of truth for
persisted schedule state.

### Preview, Apply, And Save

The v2 workflow makes the monthly schedule lifecycle explicit:

- Preview creates a candidate schedule for review.
- Apply promotes a server-side candidate into the current workspace.
- Save creates version history from the current workspace.
- Export reads the saved/current scheduling state and returns CSV.

That separation makes it easier to explain what changed, when it changed, and
which actions mutate persisted state.

### Candidate Trust

v2 hardens candidate identity and freshness:

- Candidate previews are persisted server-side and referenced by ID.
- Apply reloads the candidate for the selected tenant/month instead of trusting
  arbitrary browser-submitted schedule payloads.
- Candidate freshness fingerprints reject stale candidates after relevant
  persisted inputs change.
- API apply requires `candidate_id` and rejects arbitrary full result payloads.
- Apply guards against off-month assignments before mutating the current
  workspace.

### Bounded AI

v2 treats AI as a bounded assistant, not an autonomous scheduler:

- Refine can produce a candidate preview, but cannot directly apply or save.
- Explain is read-only and bounded to selected schedule context.
- Scheduling-only intent classification rejects non-scheduling requests.
- Scheduling-related but unsupported requests return
  understood-but-not-executable responses instead of guessing.
- The offline AI intent eval harness checks refine intent behavior across a
  fixed zh/ja/en corpus without calling the OpenAI API.

### Engineering Quality

The rewrite adds reviewer-visible engineering structure:

- CI-style local verification with Ruff and pytest.
- Focused integration tests around monthly workspace behavior, candidates,
  refine/explain, and reviewer stories.
- Remote deployment on the rented server, side-by-side with v1.
- A deployment path that keeps v2's `.env`, Docker Compose project, and SQLite
  volume separate from v1.

## Current Live Demo

The current deployment runs v2 from `/root/sched-v2` on host port `8001`.
sched-mvp v1 remains untouched on host port `8000`. v2 uses its own `.env`,
Docker Compose project, and SQLite volume. Admin is intentionally disabled in
deployment settings. Caddy provides HTTPS for the public v2 demo domain.

Public reviewer path:

`https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=zh`

Japanese UI:

`https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=ja`

## Honest Limitations

- Demo/localdev oriented rather than production SaaS hardened.
- No production auth or RBAC.
- No full tenant onboarding UI.
- Caddy HTTPS is configured for the demo domain, but production auth/RBAC is
  still out of scope.
- No full optimizer for fairness or workload balancing.
- SQLite-backed demo deployment rather than production database architecture.
- AI behavior is intentionally narrow and conservative.

## Why The Rewrite Matters

The v1 MVP answered, "Can this scheduling workflow be demonstrated?" v2 answers
a different question: "Can this scheduling workflow be trusted enough for a
reviewer to inspect the backend boundaries?" The rewrite makes the important
parts explicit: persisted inputs, generated candidates, current workspace
state, saved versions, and bounded AI assistance each have their own role.
