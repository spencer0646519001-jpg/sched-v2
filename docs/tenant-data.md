# Tenant Data And Admin Boundaries

`sched-v2` is tenant-aware and DB-first, but it is not a production SaaS
onboarding system yet. The current portfolio/demo path keeps tenant setup
explicit and internal.

## Demo Tenant Data

The demo deployment is created with:

```bash
python manage.py seed_monthly_workspace_demo
```

The command seeds the tenant slug `demo_kitchen` for the reviewer-visible
monthly workspace. It is idempotent: running it again updates the same tenant
and core demo rows rather than creating duplicate tenants.

Seeded data currently includes:

- `Tenant` row for `demo_kitchen`.
- Active worker/employee master data, including worker code, name, role, and
  scheduling profile JSON for the demo scenario.
- Station master data.
- Shift definitions.
- Worker-to-station skill rows.
- The default `ConstraintConfig` used by preview/refine/explain context.

The seed command also removes stale demo `WorkerStationSkill` rows that no
longer match the demo source data. It does not create leave requests, a current
monthly workspace, saved plan versions, or candidate previews. Those records
are created by the monthly workspace flow when a reviewer generates, applies,
saves, or refines a schedule.

The reviewer page at `/v2/monthly-workspace` reads tenant/month inputs from
the database. Preview generation, candidate freshness checks, apply, save,
export, refine, and explain all load their scheduling context from persisted
tenant-scoped rows rather than treating the browser as the source of truth.

## New Restaurant Setup

Production self-serve restaurant onboarding is intentionally not built yet.
There is no public UI for creating a tenant, inviting users, configuring roles,
or walking a restaurant through data setup.

For now, a new restaurant requires internal setup through one of these paths:

- a seed script like `seed_monthly_workspace_demo`;
- a Django fixture or direct data migration for known demo data;
- an internal-only Django admin or other private data-management process.

That boundary is intentional for a portfolio/demo deployment. The project is
showing the scheduling workflow and persistence boundaries, not a polished
multi-tenant onboarding product.

## Django Admin Boundary

The repo contains minimal Django admin registrations for core scheduling data
in `app.infra.django_app.admin`: tenants, workers, stations, shifts, worker
station skills, leave requests, constraint configs, workspaces, assignments,
plan versions, and candidate previews.

These registrations are an internal operator convenience only. The shipped
local and deployment settings do not install `django.contrib.admin` or mount an
`/admin` URL, and the public reviewer demo should focus on the monthly
workspace page.

For local-only inspection, use `app.admin_local_settings`. It extends the local
SQLite settings, enables the standard Django admin stack, and flips the private
URL flag that mounts `/admin/`:

```bat
set DJANGO_SETTINGS_MODULE=app.admin_local_settings
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open `http://127.0.0.1:8000/admin/`.

Do not expose Django admin publicly until authentication, RBAC, tenant access
control, audit expectations, and operational ownership are designed. Even then,
treat it as an internal data-management tool, not as the production
tenant-management product. `RefineRequest` remains outside the initial admin
registration because it stores user-entered scheduling text and parsed preview
payloads.
