# Demo Deployment

This project is ready for a staged portfolio/demo deployment, not a production
SaaS deployment. The initial deployment target is the same rented server that
currently hosts sched-mvp v1, but v2 must run as a fully separate app until it
is verified.

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
not a production SaaS deployment. Keep exposure intentionally limited until a
domain/TLS/auth story is added.

## Required Environment Variables

Store these on the server in v2's own uncommitted `.env` file under
`/root/sched-v2`. Do not reuse v1's `.env`, and do not commit real secrets.

```bash
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_DEBUG=False
ALLOWED_HOSTS=your.server.ip,localhost,127.0.0.1
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

Open:

```text
http://your.server.ip:8001/v2/monthly-workspace?tenant_slug=demo_kitchen&month_scope=2026-04
```

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

Smoke-test v2 before changing the public demo link/domain:

- `docker compose -p sched-v2 run --rm web python manage.py migrate` completes.
- `docker compose -p sched-v2 run --rm web python manage.py seed_monthly_workspace_demo` completes.
- The monthly workspace opens on port `8001`.
- Preview works.
- Refine works.
- Explain works.
- Applying a candidate works.
- Save and CSV export work.
- OpenAI environment variables are not exposed in the page, logs, screenshots,
  rendered Compose output, or committed files.

## Phase 3: Make V2 The Only Public Demo

After v2 is verified:

- Point the main demo link/domain to v2.
- Stop v1.
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
export ALLOWED_HOSTS=your.server.ip,localhost,127.0.0.1
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
- Set OpenAI model variables for real refine/explain behavior.
- Confirm Docker Compose is installed on the server.
- Run `docker compose -p sched-v2 build`.
- Run `docker compose -p sched-v2 run --rm web python manage.py migrate`.
- Run `docker compose -p sched-v2 run --rm web python manage.py seed_monthly_workspace_demo`.
- Start with `docker compose -p sched-v2 up -d`.
- Open the seeded workspace URL on port `8001`.
- Generate a preview, apply it once, refine, explain, save, and export CSV.
- Confirm the v2 Docker volume is separate from any v1 volume.
- Confirm OpenAI secrets are not visible in public output.
- Only after verification, move the main public demo link/domain to v2 and stop
  v1.

## Remaining Limitations

- SQLite is for the demo deployment only.
- There is no production auth, RBAC, or tenant access-control layer yet.
- The app is currently single-demo-tenant oriented.
- There is no Caddy/domain/TLS setup in this PR.
- There is no automated remote SSH deployment in this PR.
- There is no production hardening in this PR.
- Candidate preview cleanup and retention are still deferred.
