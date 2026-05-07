# Setup

This page covers how to run the project locally, either with Docker Compose or with local Python processes.

## Prerequisites

- Docker and Docker Compose
- Python `3.13`
- `uv`

If you only use Docker Compose, Python and `uv` are optional.

## Docker quickstart

1. Create the real Dockerfile.

```bash
cp Dockerfile.example Dockerfile
```

2. Create the environment file.

```bash
cp .env.example .env
```

3. Generate a Fernet key for encrypted connector configuration.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

4. Put that value in `INTEGRATION_CONFIG_ENCRYPTION_KEY` inside `.env`.

5. Review the default credentials in `.env` before exposing anything outside localhost:

- `KEYCLOAK_ADMIN`
- `KEYCLOAK_ADMIN_PASSWORD`
- `KEYCLOAK_DEV_USER_PASSWORD`
- `KEYCLOAK_DEV_ADMIN_PASSWORD`
- `FLOWER_BASIC_AUTH`
- `FLOWER_COOKIE_SECRET`
- `GRAFANA_ADMIN_PASSWORD`

6. Start the stateful dependencies first.

```bash
docker compose up --build -d db redis
```

7. Apply database migrations.

```bash
docker compose run --rm migrate
```

8. Start the application runtimes.

```bash
docker compose up -d api mcp worker beat flower prometheus grafana
```

The Compose example automatically starts Keycloak and imports the local `washing-machine` realm from [../config/keycloak/washing-machine-realm.json](../config/keycloak/washing-machine-realm.json).
It also initializes a shared Postgres database named `washing_machine` with separate `app` and `keycloak` schemas.

## Local URLs

- API: `http://localhost:8000`
- Swagger shell: `http://localhost:8000/`
- MCP: `http://localhost:8001/mcp`
- MCP health: `http://localhost:8001/health`
- Keycloak: `http://localhost:8080`
- Flower: `http://localhost:5555`
- Grafana: `http://localhost:3000`

## Local dev accounts

The default Keycloak realm import creates:

- `reader`: gets the role named by `OIDC_USER_ROLE_NAME`
- `platform-admin`: gets the roles named by `OIDC_USER_ROLE_NAME` and `OIDC_ADMIN_ROLE_NAME`

The usernames and passwords are driven by `.env`.

## Keycloak import caveat

Keycloak startup import only creates a realm when it does not already exist. If you change [../config/keycloak/washing-machine-realm.json](../config/keycloak/washing-machine-realm.json), those changes will not overwrite an existing realm automatically.

For local development, use one of these approaches:

- delete the `washing-machine` realm from the Keycloak admin console and restart `keycloak`
- recreate the `keycloak` schema in the shared Postgres database, then restart `keycloak`
- keep the realm stable and only vary secrets through `.env` placeholders

Use `docker compose down -v` only if you want a full local reset of every persisted service, including both the app and Keycloak data stored in Postgres.

## Local Python workflow

If you want to run the app processes directly on your machine while keeping infra in Docker:

1. Sync dependencies.

```bash
uv sync --dev
```

2. Prepare `.env` from the example as shown above.

3. Start infra only.

```bash
docker compose up -d db redis keycloak
```

4. Apply migrations from the host.

```bash
uv run alembic upgrade head
```

5. Start the API.

```bash
uv run uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

6. Start the MCP gateway in another terminal.

```bash
uv run uvicorn app.mcp.main:app --reload --host 0.0.0.0 --port 8001
```

7. Start the worker in another terminal.

```bash
uv run celery -A app.worker.celery.celery_app worker --loglevel=INFO --pool=solo
```

8. Start beat in another terminal.

```bash
uv run celery -A app.beat.celery.celery_app beat --loglevel=INFO
```

9. Optional: start Flower.

```bash
uv run celery -A app.worker.celery.celery_app flower
```

When using the local Python workflow, keep `MCP_PRODUCT_API_BASE_URL=http://127.0.0.1:8000` or another host-visible API URL.

## Development-only mock routes

Set `APP_ENV=dev` when you want the typed mock connectors to appear in Swagger:

- mock provisioner routes
- mock provider routes

Those routes are intended for local development and tests only.

## Running tests

Run the full suite:

```bash
uv run pytest -q
```

Run a focused subset:

```bash
uv run pytest tests/test_auth.py tests/test_api.py -q
```

## Suggested smoke checks

After startup, verify:

- `GET /health` returns `200`
- `GET /metrics` returns `200` when Prometheus API exposure is enabled
- `GET /` serves the Swagger HTML shell
- logging into Swagger works through Keycloak when `OIDC_ENABLED=true`
- `GET /v1/platforms` works with a read role token
- `POST /v1/platforms` is forbidden for the read role and allowed for the admin role
- `POST /mcp` is rejected without a token and accepted with a read role token

## Local cleanup

Stop the stack:

```bash
docker compose down
```

Stop and delete volumes:

```bash
docker compose down -v
```

The second command deletes the local Postgres, Redis, Grafana, Prometheus, and Keycloak state.
