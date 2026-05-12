# Deployment

This page describes the deployment model used by the example stack and the main points to preserve in shared environments.

## Reference deployment model

The repository ships a local reference topology in [../docker-compose.example.yml](../docker-compose.example.yml). It is not a production orchestrator manifest, but it shows the intended runtime split and startup order.

The application image is defined in [../Dockerfile.example](../Dockerfile.example).

## Container image

The image:

- starts from `python:3.13-slim`
- installs dependencies with `uv`
- builds a project virtualenv in `/opt/venv`
- runs as user `1000`
- is reused for `api`, `mcp`, `worker`, `beat`, and the `migrate` job

At runtime, the image uses binaries from `/opt/venv/bin` rather than invoking `uv`.

## Service roles

| Service | Stateful | Purpose |
| --- | --- | --- |
| `db` | yes | Shared Postgres database for the app (`app` schema) and local Keycloak (`keycloak` schema) |
| `redis` | yes | Celery broker and result backend |
| `keycloak` | yes | Local OIDC provider |
| `migrate` | no | One-shot Alembic migration job |
| `api` | no | Public REST API |
| `mcp` | no | Read-only MCP gateway |
| `worker` | no | Celery worker |
| `beat` | no | Celery Beat scheduler |
| `flower` | no | Celery operational UI |
| `prometheus` | yes | Metrics scraping and storage |
| `grafana` | yes | Dashboard UI |

## Startup order

Recommended rollout order:

1. Start databases and Redis
2. Start Keycloak if local OIDC is part of the environment
3. Run `migrate`
4. Start `api`
5. Start `worker`
6. Start `beat`
7. Start `mcp`
8. Start observability services

The Compose example encodes most of this order with health checks and `depends_on`.

## Local Keycloak realm import

The local stack mounts [../config/keycloak/washing-machine-realm.json](../config/keycloak/washing-machine-realm.json) into `/opt/keycloak/data/import` and starts Keycloak with `--import-realm`.

Important behavior:

- startup import creates the realm only if it does not already exist
- changing the realm JSON does not overwrite an existing imported realm
- credentials and role names still remain configurable through `.env` placeholders

For shared environments, either:

- manage Keycloak separately and point the app to that external issuer
- or treat the local realm import as bootstrap-only and handle realm lifecycle outside the application deploy

## Exposed ports in the example stack

| Port | Service | Notes |
| --- | --- | --- |
| `8000` | API | Public REST API and Swagger |
| `8001` | MCP | Read-only MCP transport |
| `8080` | Keycloak | Local OIDC provider |
| `5432` | Postgres | Shared application and Keycloak database |
| `6379` | Redis | Celery broker |
| `5555` | Flower | Queue and task UI |
| `3000` | Grafana | Dashboard UI |
| `9101` | Worker | Celery Prometheus exporter |

Prometheus itself stays internal to the Compose network in the example setup.

## Production recommendations

- Keep `APP_ENV=prod`
- Use managed or hardened Postgres and Redis where possible
- Put API, MCP, and Keycloak behind TLS termination
- Do not expose Prometheus, Flower, or the Keycloak management port broadly
- Rotate all default passwords and secrets before any shared deployment
- Keep `DATABASE_ENCRYPTION_KEY` in a secret manager
- Use an external OIDC provider if Keycloak should not be part of your app deployment

## Scaling guidance

### API and MCP

- API instances can scale horizontally
- MCP instances can scale horizontally
- both are stateless apart from their dependency on the shared DB and OIDC provider

### Worker

- workers can scale horizontally
- per-machine metric fan-out is designed to distribute naturally across workers

### Beat

- prefer a single beat instance
- multiple beat instances can create duplicate dispatcher tasks
- downstream dispatchers now reserve rows safely, but a single beat still keeps operations simpler

## Deployment checklist

Before rollout:

- build the image
- verify `.env` or platform secrets
- run migrations
- confirm OIDC issuer and role names
- confirm `DATABASE_ENCRYPTION_KEY`

After rollout:

- check `GET /health`
- verify Swagger login if OIDC is enabled
- verify a read token can call one GET endpoint
- verify an admin token can trigger one manual task
- verify worker and beat metrics are visible to Prometheus

## Upgrades

Recommended sequence:

1. deploy or upgrade the image
2. run Alembic migrations first
3. restart or roll `api`, `worker`, `beat`, and `mcp`
4. verify health and one end-to-end sync path

Be careful when upgrading:

- database schema and code should move together
- encrypted config depends on a stable Fernet key
- Keycloak realm JSON changes do not retroactively patch an existing imported realm

## Adapting the stack to another orchestrator

If you move from Docker Compose to Kubernetes or another platform, preserve:

- the runtime split between API, MCP, worker, and beat
- the migration step before application traffic
- the shared Postgres and Redis dependencies
- the OIDC issuer reachability from both browsers and server-side discovery
- the Prometheus scraping surfaces
