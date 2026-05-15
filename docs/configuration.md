# Configuration

This page documents the main environment variables used by the application and the local stack.

## Configuration model

- The API, worker, and beat use [../internal/infra/config/settings.py](../internal/infra/config/settings.py).
- Flower uses the minimal Celery settings in [../app/flower/main.py](../app/flower/main.py).
- The MCP gateway uses [../app/mcp/config/settings.py](../app/mcp/config/settings.py).
- OIDC auth uses [../internal/infra/auth/settings.py](../internal/infra/auth/settings.py).
- The local Keycloak stack consumes the same `.env` file through [../docker-compose.example.yml](../docker-compose.example.yml).

## Core runtime settings

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `APP_NAME` | `Washing Machine` | API, MCP | Displayed in Swagger and app metadata. |
| `APP_ENV` | `prod` | API | `dev` exposes mock connector routes. |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@db:5432/washing_machine` | API, worker, beat, migrations | Shared Postgres database used by the app and local Keycloak. |
| `DATABASE_SCHEMA` | `app` | API, worker, beat, migrations | PostgreSQL schema selected for application tables and Alembic state. |
| `DATABASE_ENCRYPTION_KEY` | required | API, worker, beat | Fernet key used for encrypted connector config at rest. |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | API, worker, beat, Flower | Broker for task publication and delivery. |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | Worker, Flower | Celery result backend. |
| `CELERY_TASK_EXECUTION_RETENTION_DAYS` | `90` | Worker maintenance task | Number of days to keep rows in `celery_task_executions`. |
| `APPLICATION_RETENTION_DAYS` | `15` | Worker maintenance task | Number of days to keep application projection rows since their last `updated_at`. |
| `MACHINE_RETENTION_DAYS` | `15` | Worker maintenance task | Number of days to keep machine inventory rows since their last `updated_at`. |

## OIDC and RBAC settings

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `OIDC_ENABLED` | `true` in `.env.example` | API, MCP | Turns auth on or off. |
| `OIDC_ISSUER_URL` | `http://localhost:8080/realms/washing-machine` | API, MCP | Public issuer used for token validation and Swagger endpoints. |
| `OIDC_DISCOVERY_URL` | `http://keycloak:8080/realms/washing-machine/.well-known/openid-configuration` | API, MCP | Optional explicit discovery URL. Useful when discovery is internal but browsers must see a public issuer. |
| `OIDC_JWKS_CACHE_TTL_SECONDS` | `300` | API, MCP | TTL for discovery and JWKS cache entries. |
| `OIDC_ROLE_CLAIM_PATHS` | `realm_access.roles,resource_access.*.roles,roles` | API, MCP | Dotted claim paths used to extract roles, with `*` wildcard support. |
| `OIDC_USER_ROLE_NAME` | `user` | API, MCP, Keycloak import | Read-only role label. |
| `OIDC_ADMIN_ROLE_NAME` | `admin` | API, MCP, Keycloak import | Write/execution role label. |
| `OIDC_SWAGGER_CLIENT_ID` | `washing-machine-swagger` | API, Keycloak import | Public client used by the Swagger UI. |
| `OIDC_SWAGGER_USE_PKCE` | `true` | API | Enables PKCE in Swagger UI. |
| `OIDC_SWAGGER_SCOPES` | `openid profile email` | API | OAuth scopes requested by Swagger UI. |

## Auth behavior notes

- The HTML Swagger shell at `/` stays reachable so the browser can initiate login.
- The OpenAPI JSON at `/v1/openapi.json` requires the read role when OIDC is enabled.
- The auth layer validates signature, issuer, `exp`, and `nbf`.
- Audience is intentionally ignored.
- The MCP gateway only forwards the incoming `Authorization` header.

## Local Keycloak settings

These variables are only for the local Keycloak stack and realm import:

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `KEYCLOAK_REALM` | `washing-machine` | Keycloak import | Realm name in the local stack. |
| `KEYCLOAK_ADMIN` | `admin` | Keycloak container | Bootstrap admin username for the master realm. |
| `KEYCLOAK_ADMIN_PASSWORD` | `change-me` | Keycloak container | Bootstrap admin password. |
| `KEYCLOAK_DEV_USER_PASSWORD` | `reader-change-me` | Keycloak import | Password for the fixed read-only dev account `reader`. |
| `KEYCLOAK_DEV_ADMIN_PASSWORD` | `platform-admin-change-me` | Keycloak import | Password for the fixed admin dev account `platform-admin`. |

The local Compose stack points Keycloak at the same `washing_machine` PostgreSQL database and selects the `keycloak` schema through `KC_DB_SCHEMA`.

## MCP settings

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `MCP_API_BASE_URL` | `http://api:8000` in Docker | MCP | Base URL of the product API that the MCP gateway proxies. |
| `MCP_API_TIMEOUT_SECONDS` | `30` | MCP | Timeout for downstream API calls. |
| `MCP_MASK_ERROR_DETAILS` | `true` | MCP | Masks unexpected FastMCP error details. Downstream product API errors are still returned as bounded public messages. |

## Scheduler and batching settings

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `SCHEDULER_TICK_SECONDS` | `60` | Beat | Frequency of the provisioner dispatcher task. |
| `APPLICATION_INVENTORY_SYNC_TICK_SECONDS` | `3600` | Beat | Frequency of the inventory discovery projection rebuild. |
| `APPLICATION_METRICS_SYNC_TICK_SECONDS` | `3600` | Beat | Frequency of the due-application metrics dispatcher. |
| `APPLICATION_METRICS_SYNC_WINDOW_DAYS` | `5` | Beat, workers | Max target delay between two metrics syncs for one application. |
| `APPLICATION_METRICS_SYNC_BATCH_SIZE` | `0` | Beat, workers | `0` means auto-calculate a batch size from the window and tick frequency. |
| `APPLICATION_METRICS_SYNC_RETRY_AFTER_SECONDS` | `3600` | Beat, workers | Delay before retrying an application already marked as scheduled. |

## Machine optimization settings

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `FLAVOR_OPTIMIZATION_WINDOW_SIZE` | `30` | API, worker | Maximum number of latest stored samples read per scope (`cpu`, `ram`, `disk`) when computing an optimization. Calculations still run with fewer samples when at least one sample exists. |
| `FLAVOR_OPTIMIZATION_MIN_CPU` | `1` | API, worker | Lower bound for proposed CPU targets. Must stay positive and lower than or equal to `FLAVOR_OPTIMIZATION_MAX_CPU`. |
| `FLAVOR_OPTIMIZATION_MAX_CPU` | `64` | API, worker | Catalog upper bound for proposed CPU targets. Calculated targets above this keep the current CPU recommendation instead of clamping to the maximum. |
| `FLAVOR_OPTIMIZATION_MIN_RAM_MB` | `2048` | API, worker | Lower bound for proposed RAM targets. Must be a multiple of `1024`. |
| `FLAVOR_OPTIMIZATION_MAX_RAM_MB` | `262144` | API, worker | Catalog upper bound for proposed RAM targets. Calculated targets above this keep the current RAM recommendation instead of clamping to the maximum. Must be a multiple of `1024`. |

Behavior notes:

- the optimization projection stores the `window_size` and CPU/RAM bounds used for the current recommendation
- changing one of these variables only affects future recalculations
- existing optimization rows are not backfilled automatically after a config change
- a later refresh updates the stored optimization even if the public API target stays the same, because the calculation context changed

## Observability settings

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `PROMETHEUS_API_ENABLED` | `true` | API | Enables the API `/metrics` route. |
| `PROMETHEUS_API_PATH` | `/metrics` | API | Unprefixed metrics route. |
| `CELERY_PROMETHEUS_ENABLED` | `true` | Worker, beat | Enables the Celery Prometheus exporter. |
| `CELERY_PROMETHEUS_PORT` | `9101` | Worker, beat | Exporter port. |
| `FLOWER_BASIC_AUTH` | `admin:change-me` | Flower | Basic auth for the Flower UI. |
| `FLOWER_COOKIE_SECRET` | `change-me-in-production` | Flower | Cookie signing secret. |
| `GRAFANA_ADMIN_USER` | `admin` | Grafana | Grafana admin username. |
| `GRAFANA_ADMIN_PASSWORD` | `change-me` | Grafana | Grafana admin password. |

## Important conventions

### `APP_ENV`

- `prod`: normal runtime behavior
- `test`: test-only environment value
- `dev`: enables mock connector routes in the API

### `OIDC_ROLE_CLAIM_PATHS`

This value is a comma-separated list of dotted paths. Examples:

- `realm_access.roles`
- `roles`
- `resource_access.*.roles`

The wildcard `*` expands over every value in a dict or list.

### `DATABASE_ENCRYPTION_KEY`

- Must be a valid Fernet key
- Is required at startup
- Is used to decrypt connector config stored in the database
- Invalid ciphertext now fails closed instead of being treated as plaintext

## Configuration strategy

Recommended practice:

- keep `.env.example` as the canonical list of variables
- use `.env` for local development only
- inject real secrets through your deployment platform in shared environments
- keep role names configurable through `OIDC_USER_ROLE_NAME` and `OIDC_ADMIN_ROLE_NAME`
- keep `APP_ENV=prod` outside local development
