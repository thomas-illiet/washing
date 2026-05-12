# Documentation

This directory is the long-form documentation for the project. The root [README](../README.md) stays focused on the overview and quickstart, while these pages go deeper into setup, architecture, deployment, operations, and feature behavior.

## Recommended reading order

1. [Setup](./setup.md)
2. [Configuration](./configuration.md)
3. [Architecture](./architecture.md)
4. [Machine Recommendations](./recommendations.md)
5. [Deployment](./deployment.md)
6. [Operations](./operations.md)
7. [Celery Task Map](./celery-task-map.md)

## Document map

- [Setup](./setup.md): local Docker workflow, local Python workflow, tests, and smoke checks
- [Configuration](./configuration.md): environment variables, auth configuration, scheduler tuning, and observability settings
- [Architecture](./architecture.md): runtime topology, code organization, domain model, and main execution flows
- [Machine Recommendations](./recommendations.md): recommendation inputs, API endpoints, calculation rules, statuses, and operations
- [Deployment](./deployment.md): image, runtime topology, rollout order, scaling notes, and production checklist
- [Operations](./operations.md): migrations, logs, health checks, troubleshooting, and maintenance routines
- [Celery Task Map](./celery-task-map.md): full task inventory and enqueue flow

## Source-of-truth files

- Runtime env defaults: [../.env.example](../.env.example)
- Local stack topology: [../docker-compose.example.yml](../docker-compose.example.yml)
- Container image: [../Dockerfile.example](../Dockerfile.example)
- Keycloak realm import: [../config/keycloak/washing-machine-realm.json](../config/keycloak/washing-machine-realm.json)
- App settings: [../internal/infra/config/settings.py](../internal/infra/config/settings.py)
- OIDC settings: [../internal/infra/auth/settings.py](../internal/infra/auth/settings.py)
