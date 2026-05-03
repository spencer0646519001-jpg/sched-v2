# Demo Deployment

This project is deployed as a staged portfolio/demo deployment, not a
production SaaS deployment. The deployment target is the same rented server that
hosts sched-mvp v1, with v2 running as a fully separate app so v1 remains
available as a legacy/reference project.

## Current Deployment Status

The current demo is deployed side-by-side on the same rented DigitalOcean
server:

- sched-mvp v1 remains untouched on host port `8000`.
- sched-v2 is deployed under `/root/sched-v2`.
- The remote v2 container runs on host port `8001`, mapped to container port
  `8000`.
- v2 uses its own uncommitted `.env`, Docker Compose project, and SQLite volume.
- Caddy terminates HTTPS for `sched.spencerailab.com` and proxies the public v2
  demo domain to the v2 app.
- v2 admin is intentionally disabled in deploy settings.

Public reviewer URL:

```text
https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=zh
```

Japanese UI:

```text
https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=ja
```

Latest smoke test passed:

- Monthly workspace `GET` returned `200`.
- Preview, refine, apply, save, and explain `POST` requests returned `200`.
- CSV export returned `200`.
- `/admin/` returned `404`.

## Runtime Design

- Django starts through `manage.py`.
- Local development keeps using `app.localdev_settings`.
- Demo deployment uses `app.deploy_settings`, which reads server environment
  variables and stores SQLite at `/data/sched-v2.sqlite3` by default.
- Docker Compose mounts `/data` as the project-scoped SQLite volume
  `sched_v2_sqlite`, so the demo database survives container rebuilds and
  restarts.
- The container command is:

```bash
python manage.py runserver 0.0.0.0:8000 --noreload
```

The host port is separate from the container port. In the initial side-by-side
deployment, host port `8001` maps to container internal port `8000`; this avoids
colliding with sched-mvp v1, which keeps host port `8000`.

`runserver` is acceptable here because this is a rented-server portfolio demo,
not a production SaaS deployment. Caddy owns the public HTTPS endpoint, and
production auth/RBAC remains intentionally out of scope for this deployment.

## Required Environment Variables

Store these on the server in v2's own uncommitted `.env` file under
`/root/sched-v2`. Do not reuse v1's `.env`, and do not commit real secrets.

```bash
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_DEBUG=False
ALLOWED_HOSTS=sched.spencerailab.com,your.server.ip,localhost,127.0.0.1
OPENAI_API_KEY=sk-...
OPENAI_REFINE_MODEL=gpt-4o-mini
OPENAI_EXPLAIN_MODEL=gpt-4o-mini
SCHED_V2_PORT=8001
```

Notes:

- `DJANGO_SECRET_KEY` is required by `app.deploy_settings`.
- `DJANGO_DEBUG` should be `False` for the demo server.
- `ALLOWED_HOSTS` is a comma-separated list of hostnames/IPs used to reach the
  app.
- `OPENAI_API_KEY`, `OPENAI_REFINE_MODEL`, and `OPENAI_EXPLAIN_MODEL` enable
  real refine/explain model calls. Without an API key, the app falls back to
  noop model clients, so preview/apply/save/export and offline eval remain
  safe.
- Do not paste rendered `docker compose config` output into public places; it
  expands environment values.

## Phase 1: Temporary Side-By-Side Deployment

Keep v1 untouched while bringing up v2:

- v1 stays in `/root/sched-mvp`.
- v1 keeps host port `8000`.
- v2 uses `/root/sched-v2`.
- v2 uses host port `8001`.
- v2 uses its own `/root/sched-v2/.env`.
- v2 uses its own SQLite database and Docker volume.
- v2 uses its own Docker Compose project name: `sched-v2`.
- Do not reuse v1's folder, `.env`, database, volume, container names, or
  Compose project name.

From `/root/sched-v2`, build the image, migrate the v2 SQLite database, seed the
v2 demo data, and start the app:

```bash
docker compose -p sched-v2 build
docker compose -p sched-v2 run --rm web python manage.py migrate
docker compose -p sched-v2 run --rm web python manage.py seed_monthly_workspace_demo
docker compose -p sched-v2 up -d
```

Open the public v2 demo:

```text
https://sched.spencerailab.com/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04&ui_lang=zh
```

The seed command creates the `demo_kitchen` tenant and DB-backed demo inputs:
workers, stations, shifts, worker station skills, worker scheduling profile
JSON, and the default constraint config. It does not create a current monthly
workspace; reviewers create that by generating a preview and applying it once.
See [Tenant Data And Admin Boundaries](tenant-data.md) for the full data setup
story.

To inspect logs:

```bash
docker compose -p sched-v2 logs -f web
```

To stop v2 without deleting the v2 SQLite database volume:

```bash
docker compose -p sched-v2 down
```

Only delete the v2 volume if you intentionally want to reset the v2 demo
database:

```bash
docker compose -p sched-v2 down -v
```

## Phase 2: Verify V2

Smoke-test v2 before changing or promoting the public demo link/domain:

- `docker compose -p sched-v2 run --rm web python manage.py migrate` completes.
- `docker compose -p sched-v2 run --rm web python manage.py seed_monthly_workspace_demo` completes.
- The monthly workspace opens through the Caddy HTTPS domain.
- Preview works.
- Refine works.
- Explain works.
- Applying a candidate works.
- Save and CSV export work.
- OpenAI environment variables are not exposed in the page, logs, screenshots,
  rendered Compose output, or committed files.

## Phase 3: Make V2 The Main Public Demo

After v2 is verified:

- Point the main demo link/domain to v2. The current public demo domain is
  `https://sched.spencerailab.com/`.
- Keep v1 available only as a legacy/reference project.
- Optionally leave `/root/sched-mvp` on the server temporarily as a rollback
  backup.
- Keep v1 on GitHub only as a legacy/reference project.
- Do not present v1 and v2 as equal live demos in portfolio material.

## Non-Docker Server Commands

If running v2 directly on the server, install dependencies in `/root/sched-v2`
and set the deployment settings module:

```bash
python -m pip install .
export DJANGO_SETTINGS_MODULE=app.deploy_settings
export DJANGO_SECRET_KEY=replace-with-a-long-random-secret
export DJANGO_DEBUG=False
export ALLOWED_HOSTS=sched.spencerailab.com,your.server.ip,localhost,127.0.0.1
export OPENAI_API_KEY=sk-...
export OPENAI_REFINE_MODEL=gpt-4o-mini
export OPENAI_EXPLAIN_MODEL=gpt-4o-mini
export SCHED_V2_SQLITE_PATH=/root/sched-v2/data/sched-v2.sqlite3
python manage.py migrate
python manage.py seed_monthly_workspace_demo
python manage.py runserver 0.0.0.0:8001 --noreload
```

Create the parent directory for `SCHED_V2_SQLITE_PATH` before running
migrations. Keep this database separate from any v1 database.

## Demo Deployment Checklist

- Confirm v1 remains untouched in `/root/sched-mvp` on host port `8000`.
- Confirm v2 is checked out separately in `/root/sched-v2`.
- Confirm `/root/sched-v2/.env` exists and is not committed.
- Set `DJANGO_SECRET_KEY` to a long random value.
- Set `DJANGO_DEBUG=False`.
- Set `ALLOWED_HOSTS` to the server IP/domain and any local loopback host used
  for health checks.
- Set `SCHED_V2_PORT=8001`.
- Configure Caddy to serve `https://sched.spencerailab.com/` and proxy to v2.
- Set OpenAI model variables for real refine/explain behavior.
- Confirm Docker Compose is installed on the server.
- Run `docker compose -p sched-v2 build`.
- Run `docker compose -p sched-v2 run --rm web python manage.py migrate`.
- Run `docker compose -p sched-v2 run --rm web python manage.py seed_monthly_workspace_demo`.
- Start with `docker compose -p sched-v2 up -d`.
- Open the seeded workspace URL through the Caddy HTTPS domain.
- Generate a preview, apply it once, refine, explain, save, and export CSV.
- Confirm the v2 Docker volume is separate from any v1 volume.
- Confirm OpenAI secrets are not visible in public output.
- Keep the main public demo link/domain pointed to v2 and keep v1 positioned as
  legacy/reference only.

## Admin And Tenant Setup Boundary

This deployment is intentionally not a production tenant-management system.
New restaurant setup currently requires internal seed scripts, fixtures, or a
private data-management process. Production self-serve onboarding, production
auth/RBAC, and a public rule editor are not part of this deployment path.

Django admin is not mounted by the shipped demo settings and should not be part
of the public reviewer surface. Minimal model registrations exist for future
internal use. The local-only `app.admin_local_settings` profile can mount
`/admin/` for private data inspection, but `app.deploy_settings` keeps admin
disabled and should not be changed to expose it publicly until authentication,
RBAC, tenant access control, and operational ownership are designed.

## Remaining Limitations

- SQLite is for the demo deployment only.
- There is no production auth, RBAC, or tenant access-control layer yet.
- The app is currently single-demo-tenant oriented, with no self-serve tenant
  onboarding UI.
- Caddy/domain/TLS exists for the demo domain, but this is still not a
  production SaaS hardening pass.
- There is no automated remote SSH deployment in this PR.
- There is no production hardening in this PR.
- Candidate preview cleanup and retention are still deferred.
