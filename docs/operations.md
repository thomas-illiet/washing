# Operations

This page groups the commands and runbooks that are useful once the project is already running.

## Routine commands

### Run migrations

```bash
uv run alembic upgrade head
```

With Docker Compose:

```bash
docker compose run --rm migrate
```

### Create a migration

```bash
uv run alembic revision --autogenerate -m "describe_change"
```

Review the generated file in `alembic/versions/` carefully before applying it.

### Run tests

```bash
uv run pytest -q
```

### Tail logs in Docker

```bash
docker compose logs -f api mcp worker beat
```

### Restart one runtime

```bash
docker compose restart api
docker compose restart worker
docker compose restart beat
docker compose restart mcp
```

## Health and visibility

### Health endpoints

- API: `GET /health`
- MCP: `GET /health` on port `8001`
- Keycloak readiness: internal `/health/ready`

### Task visibility

- API task history: `GET /v1/worker/tasks`
- API task detail: `GET /v1/worker/tasks/{task_id}`
- Flower UI: `http://localhost:5555`
- Prometheus metrics: API `/metrics` and Celery exporters

### Useful UI surfaces

- Swagger: `http://localhost:8000/`
- Flower: `http://localhost:5555`
- Grafana: `http://localhost:3000`
- Keycloak: `http://localhost:8080`

## Common maintenance tasks

### Updating the local Keycloak realm import

If you change [../config/keycloak/washing-machine-realm.json](../config/keycloak/washing-machine-realm.json):

- the running realm will not be overwritten automatically
- delete the realm in Keycloak or recreate the `keycloak` schema in the shared Postgres database
- restart `keycloak`

### Rotating passwords and local accounts

For the local stack:

- change the values in `.env` for `KEYCLOAK_DEV_USER_PASSWORD` and `KEYCLOAK_DEV_ADMIN_PASSWORD`
- restart `keycloak` if the values are only used at import time

For existing imported users, changing `.env` alone does not patch an already imported realm unless the realm is recreated. Usernames, names, and emails for the demo accounts are fixed in the realm import JSON.

### Changing role names

If you change:

- `OIDC_USER_ROLE_NAME`
- `OIDC_ADMIN_ROLE_NAME`

Then update:

- `.env`
- the external IdP configuration, or recreate the local Keycloak realm import
- any automation or test tokens that assume the previous names

### Working with encrypted connector config

Connector config is stored encrypted in the database.

Operational implications:

- keep `DATABASE_ENCRYPTION_KEY` stable
- do not rotate it casually
- corrupted ciphertext now fails closed

Changing the key without migrating stored rows will break decryption of existing configs.

### Application projection maintenance

The `applications` table is derived from `machines`.

Use cases:

- rebuild application projection: trigger `POST /v1/applications/sync?type=inventory_discovery`
- inspect machines for one projection row: `GET /v1/applications/{application_id}/machines`
- run metrics sync for one projection row: `POST /v1/applications/{application_id}/metrics/sync`
- do not treat `applications` as the source of truth for inventory

### Platform and machine diagnostics

Useful endpoints:

- platform summary: `GET /v1/platforms/{platform_id}/summary`
- latest per-scope machine metrics: `GET /v1/machines/{machine_id}/metrics/latest`
- trigger due provisioner dispatch: `POST /v1/machines/provisioners/sync`
- trigger one enabled provider dispatch: `POST /v1/machines/providers/{provider_id}/run`
- inspect provider-visible machines: `GET /v1/machines/providers/{provider_id}/machines`
- inspect provisioner machines/providers: `GET /v1/machines/provisioners/{provisioner_id}/machines` and `GET /v1/machines/provisioners/{provisioner_id}/providers`

### Machine optimization projection

Machine optimizations are stored in a versioned `machine_optimizations` table.

Behavior:

- the current row is identified with `is_current=true`
- older revisions stay in the same table with `is_current=false`
- the optimization history endpoint includes the current row as well
- optimization refreshes happen automatically after metric collection and after machine flavor changes detected by inventory

Useful endpoints:

- list optimizations: `GET /v1/machines/optimizations`
- acknowledge an optimization: `POST /v1/machines/optimizations/{optimization_id}/acknowledge`
- read current optimization: `GET /v1/machines/{machine_id}/optimizations`
- read optimization history: `GET /v1/machines/{machine_id}/optimizations/history`
- list optimizations for one application projection row: `GET /v1/applications/{application_id}/optimizations`
- enqueue a manual recalculation: `POST /v1/machines/{machine_id}/optimizations/recalculate`

Manual recalculation is useful after:

- changing `FLAVOR_OPTIMIZATION_WINDOW_SIZE`
- changing CPU or RAM min/max optimization bounds
- fixing provider visibility or connector configuration

Changing the optimization env settings does not trigger a global rebuild automatically. The new values only apply to future refreshes.

See [Machine Optimizations](./optimizations.md) for the calculation rules and response fields.

### Task history retention

Tracked Celery executions are cleaned up automatically once per day by Beat.

Behavior:

- the cleanup task deletes rows in `celery_task_executions` older than the retention window
- the default retention is `90` days
- the retention is configurable through `CELERY_TASK_EXECUTION_RETENTION_DAYS`

If you need a longer audit trail, increase the retention before the next daily cleanup runs.

### Stale machine retention

Machine inventory rows are cleaned up automatically once per day by Beat.

Behavior:

- the cleanup task deletes rows in `machines` whose `updated_at` is older than the retention window
- the default retention is `15` days
- the retention is configurable through `MACHINE_RETENTION_DAYS`
- child machine rows such as flavor history, metric samples, and versioned machine optimizations follow the delete through database cascades
- the task does not clean or rebuild `applications`

### Stale application retention

Application projection rows are cleaned up automatically once per day by Beat.

Behavior:

- the cleanup task deletes rows in `applications` whose `updated_at` is older than the retention window
- the default retention is `15` days
- the retention is configurable through `APPLICATION_RETENTION_DAYS`
- the task only touches `applications`

## Troubleshooting guide

| Symptom | Likely cause | Where to look |
| --- | --- | --- |
| `401` on Swagger API calls | missing login, invalid token, wrong issuer | API logs, OIDC settings, Keycloak login |
| `403` on POST/PATCH/DELETE | caller has only the read role | token role claims, `OIDC_ADMIN_ROLE_NAME` |
| Tasks stay `PENDING` | worker not running or broker issue | Flower, Redis, worker logs, `GET /v1/worker/tasks` |
| Old task history disappears | daily retention cleanup ran as expected | `CELERY_TASK_EXECUTION_RETENTION_DAYS`, Beat logs |
| Scheduled syncs do not happen | beat not running or schedule misconfigured | beat logs, scheduler settings, worker queue |
| Inventory updates but metrics stay empty | provider disabled, no visible providers, or placeholder connector | provider config, `applications.sync_metrics`, worker logs |
| Connector run returns no data | placeholder connector or empty upstream result | connector type, docs, expected no-op behavior |
| Keycloak realm file changes have no effect | startup import skipped because realm already exists | recreate realm or reset Keycloak DB |
| `/metrics` missing | `PROMETHEUS_API_ENABLED=false` or route path changed | `.env`, API settings |

## Known intentional behaviors

- Placeholder connectors such as `capsule`, `dynatrace`, and `prometheus` can be valid and still produce zero data.
- The Swagger HTML shell remains reachable with OIDC enabled so login can start.
- The OpenAPI JSON route itself stays protected when OIDC is enabled.
- MCP is read-only and forwards only the caller's `Authorization` header.

## Suggested incident checks

Start with this order:

1. verify `GET /health`
2. verify Redis and Postgres reachability
3. verify worker and beat logs
4. inspect `GET /v1/worker/tasks`
5. inspect Flower queue state
6. verify OIDC issuer and login flow

## Change workflow for maintainers

When changing business behavior:

1. update code
2. update or add tests
3. update the relevant document in `docs/`
4. run `uv run pytest -q`

When changing schema:

1. update ORM models
2. generate an Alembic migration with `uv run alembic revision --autogenerate -m "describe_change"`
3. review the migration manually
4. apply it on a local stack
5. run tests

If the migration history itself is squashed, reset local databases or stamp them intentionally before running `upgrade head`.
