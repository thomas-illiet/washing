# Metrics Collector

Python backend for collecting machine inventory and metrics from external products.

The stack includes:

- FastAPI for the REST API
- Celery worker for collection jobs
- Celery Beat for scheduling
- Flower for Celery control and real-time supervision
- Postgres for persistence
- Redis for the Celery broker
- Alembic for migrations
- Prometheus for API, Celery, and Flower metrics
- Grafana for observability dashboards

## Run Locally With Docker

First create a local `Dockerfile` from the template:

```bash
cp Dockerfile.example Dockerfile
```

Then create the environment file:

```bash
cp .env.example .env
```

Then generate a dedicated Fernet key for your local environment:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Update these variables before exposing monitoring:

- `FLOWER_BASIC_AUTH`
- `FLOWER_COOKIE_SECRET`
- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`
- `INTEGRATION_CONFIG_ENCRYPTION_KEY`

Then create a local `docker-compose.yml` from the example:

```bash
cp docker-compose.example.yml docker-compose.yml
```

Build the image and start dependencies:

```bash
docker compose up --build -d db redis
```

Apply migrations in the dedicated container:

```bash
docker compose run --rm migrate
```

Then start the application runtimes:

```bash
docker compose up -d api worker beat flower prometheus grafana
```

The `api`, `worker`, `beat`, and `flower` services run with a security posture close to restricted OpenShift:

- non-root user `1000:1000`
- `cap_drop: ["ALL"]`
- `read_only: true`
- `no-new-privileges:true`

Celery Beat is now fully stateless and always uses the in-memory scheduler `celery.beat:Scheduler`. Flower also runs without a persistent local database in this setup.

Available interfaces:

- API: `http://localhost:8000`
- Flower: `http://localhost:5555`
- Grafana: `http://localhost:3000`

Prometheus stays internal to the Docker Compose network by default and is not published on the host.

The real `Dockerfile` and `docker-compose.yml` are intentionally not versioned. The repo provides `*.example` files that you can copy and adapt locally.

The Docker image uses `uv` only during the build. At runtime it relies on binaries installed in `/opt/venv/bin`, which avoids cache writes at startup.

## Project Structure

The codebase is split by runtime, in a layout inspired by Go projects:

- `app/` contains only executable applications.
- `app/api`: FastAPI entrypoint, HTTP dependencies, and routes.
- `app/worker`: Celery worker runtime and all executable tasks, organized in `app/worker/tasks/{scheduler,applications,inventory,metrics}`.
- `app/beat`: Celery Beat runtime and schedule definitions only, with no task implementation.
- `internal/usecases`: business logic shared by the API, beat, and workers.
- `internal/domain`: reserved place for pure domain rules when they need stronger isolation.
- `internal/infra`: configuration, database, Celery broker, connectors, and observability.
- `internal/contracts/http`: HTTP input and output schemas.

Useful endpoints:

- `GET /health`
- `GET /`: Swagger documentation
- OpenAPI JSON: `GET /v1/openapi.json`
- Management: `/v1/platforms`, `/v1/applications`, `GET /v1/machines`, `GET/DELETE /v1/machines/{id}`, `/v1/machines/providers`, `/v1/machines/provisioners`
- Association: `POST /v1/machines/providers/{provider_id}/provisioners/{provisioner_id}`
- Activation: `POST /v1/machines/providers/{id}/enable|disable`, `POST /v1/machines/provisioners/{id}/enable|disable`
- Manual jobs: `POST /v1/machines/provisioners/{id}/run`, `POST /v1/applications/{id}/sync`
- Application sync: `POST /v1/applications/sync-due` to asynchronously trigger the dispatcher
- Business metrics: `GET /v1/machines/{machine_id}/metrics?type=cpu|ram|disk`, `GET /v1/machines/metrics?type=cpu|ram|disk`
- Prometheus: `GET /metrics`

All business HTTP routes are versioned under `/v1`. Operational endpoints `/health` and `/metrics` remain unprefixed.

All `GET` endpoints that return a list use the same paginated envelope:

```json
{
  "items": [],
  "offset": 0,
  "limit": 100,
  "total": 0
}
```

Collections and sublists support `offset` and `limit` with `offset >= 0` and `limit >= 1`.

Typed sub-routes for integrations:

- Provisioners: `POST /v1/machines/provisioners/capsule`, `GET/PATCH /v1/machines/provisioners/{id}/capsule`, `POST /v1/machines/provisioners/dynatrace`, `GET/PATCH /v1/machines/provisioners/{id}/dynatrace`
- Providers: `POST /v1/machines/providers/prometheus`, `GET/PATCH /v1/machines/providers/{id}/prometheus`, `POST /v1/machines/providers/dynatrace`, `GET/PATCH /v1/machines/providers/{id}/dynatrace`

Generic `/v1/machines/providers` and `/v1/machines/provisioners` responses never expose the `config` field. Secrets are stored encrypted in the database and tokens are never returned by the API.
One provisioner can be linked to only one provider of a given `type`.
Providers and provisioners are created disabled by default and must be enabled through their dedicated endpoints.
Machines are discovered and synchronized through provisioners; the public API does not expose `POST` or `PATCH` on `/v1/machines`.

Swagger documentation is exposed at `/` and loads the OpenAPI schema from `/v1/openapi.json`. The default FastAPI `/docs` and `/redoc` routes are disabled.

## Observability

Prometheus can scrape:

- FastAPI API: `http://localhost:8000/metrics`
- Celery worker: `http://localhost:9101/metrics`
- Celery Beat: `http://beat:9101/metrics` from the Docker network
- Flower: `http://flower:5555/metrics` from the Docker network

Flower provides the Celery operational view:

- worker status
- task history and state
- queues, pending tasks, and scheduled tasks
- Celery remote-control actions

Grafana automatically loads a `Celery Monitoring` dashboard with:

- task throughput by state
- task duration percentiles
- number of in-progress tasks
- worker status
- Beat status
- health of Prometheus scrape targets

Main metrics:

- `api_http_requests_total`
- `api_http_request_duration_seconds`
- `celery_tasks_total`
- `celery_task_duration_seconds`
- `celery_tasks_in_progress`
- `celery_worker_up`
- `celery_beat_up`

The Prometheus `/metrics` endpoint does not replace the business endpoints `/v1/machines/{machine_id}/metrics` and `/v1/machines/metrics`.

Default access:

- Flower uses HTTP Basic authentication defined through `FLOWER_BASIC_AUTH`
- Grafana uses `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`
- Prometheus is reachable only from other Compose containers unless you explicitly publish a port

## Machine Metrics

Metrics are stored daily, with a single row per machine, provider, and day:

- `machine_cpu_metrics`
- `machine_ram_metrics`
- `machine_disk_metrics`

Each table follows the same business shape: `machine_id`, `provider_id`, `date`, `value`.

The `GET /v1/machines/{machine_id}/metrics` and `GET /v1/machines/metrics` endpoints require `type=cpu|ram|disk`, support `start` and `end` in `YYYY-MM-DD` format, as well as `offset` and `limit`, and return the `{items, offset, limit, total}` envelope. Collections perform a daily upsert: rerunning a collection on the same day updates the existing row.

## Applications

The `applications` table contains one row per application, environment, and region. Machines can reference this table through `application_id`.

Each application must be synchronized at least once every 5 days. Celery Beat triggers a dedicated dispatcher that selects only a small batch of due applications on each tick, spreading the load instead of synchronizing everything at once.
The `POST /v1/applications/sync-due` endpoint enqueues that dispatcher in Celery; the API no longer performs the dispatch directly in its own process.

Applications do not expose a public HTTP `PATCH` route. Application data changes must go through synchronization tasks.

Useful variables:

- `APPLICATION_SYNC_TICK_SECONDS`: frequency of the application sync dispatcher.
- `APPLICATION_SYNC_WINDOW_DAYS`: maximum window between synchronizations, default `5` days.
- `APPLICATION_SYNC_BATCH_SIZE`: if `0`, the batch size is computed automatically to spread all applications across the window.
- `APPLICATION_SYNC_RETRY_AFTER_SECONDS`: delay before rescheduling a row that was already queued but not yet synchronized.

## MVP Connectors

Two historical stub connectors are available:

- `mock_inventory` to discover machines
- `mock_metric` to generate CPU/RAM/Disk samples

The new typed integrations exposed by the API are:

- Provisioners: `capsule`, `dynatrace`
- Providers: `prometheus`, `dynatrace`

Example internal `mock_inventory` config:

```json
{
  "machines": [
    {
      "external_id": "vm-1",
      "hostname": "vm-1",
      "application_name": "billing",
      "region": "eu-west-1",
      "environment": "dev",
      "cpu": 2,
      "ram_gb": 8,
      "disk_gb": 80
    }
  ]
}
```

Example internal `mock_metric` config:

```json
{
  "value": 42
}
```

## Development

```bash
uv python install 3.13
uv sync --group dev
uv run pytest
```

To apply migrations against Postgres:

```bash
uv run alembic upgrade head
```

The project targets Python 3.13. The `INTEGRATION_CONFIG_ENCRYPTION_KEY` key must be present at runtime for the API, worker, beat, and during Alembic migrations.

Run runtimes manually:

```bash
uv run uvicorn app.api.main:app --reload
uv run celery -A app.worker.celery.celery_app worker --loglevel=INFO --pool=solo
uv run celery -A app.beat.celery.celery_app beat --loglevel=INFO
uv run celery -A app.worker.celery.celery_app flower
```
