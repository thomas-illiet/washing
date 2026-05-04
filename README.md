# Metrics Collector

Backend Python pour collecter l'inventaire machines et des métriques depuis des produits externes.

La stack contient :

- FastAPI pour l'API REST
- Celery worker pour les jobs de collecte
- Celery Beat pour le scheduler
- Flower pour le pilotage et la supervision temps réel de Celery
- Postgres pour la persistance
- Redis pour le broker Celery
- Alembic pour les migrations
- Prometheus pour les métriques API, Celery et Flower
- Grafana pour les dashboards d'observabilité

## Lancer en local avec Docker

Créer d'abord un `Dockerfile` local à partir du template :

```bash
cp Dockerfile.example Dockerfile
```

Créer ensuite le fichier d'environnement :

```bash
cp .env.example .env
```

Variables à adapter avant d'exposer le monitoring :

- `FLOWER_BASIC_AUTH`
- `FLOWER_COOKIE_SECRET`
- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`

Créer ensuite un `docker-compose.yml` local à partir de l'exemple :

```bash
cp docker-compose.example.yml docker-compose.yml
```

```bash
docker compose up --build
```

Interfaces disponibles :

- API : `http://localhost:8000`
- Flower : `http://localhost:5555`
- Grafana : `http://localhost:3000`

Prometheus reste interne au réseau Docker Compose par défaut et n'est pas publié sur l'hôte.

Le `Dockerfile` réel et le `docker-compose.yml` réel ne sont pas versionnés volontairement. Le repo fournit des fichiers `*.example` à copier et adapter localement.

L'image Docker et les commandes du compose d'exemple utilisent `uv` pour la résolution, l'installation et l'exécution.

## Structure du projet

Le code est désormais séparé par runtime, dans un style proche des projets Go :

- `app/` ne contient que les applications exécutables.
- `app/api` : point d'entrée FastAPI, dépendances HTTP et routes.
- `app/worker` : runtime Celery worker et tâches d'exécution.
- `app/beat` : runtime Celery Beat et tâches de dispatch planifiées.
- `internal/usecases` : logique métier mutualisée entre API, beat et workers.
- `internal/domain` : emplacement réservé aux règles métier pures quand elles doivent être isolées.
- `internal/infra` : config, base de données, broker Celery, connecteurs, observabilité.
- `internal/contracts/http` : schémas d'entrée et de sortie HTTP.

Endpoints utiles :

- `GET /health`
- `GET /docs`
- CRUD : `/platforms`, `/applications`, `/machines`, `/providers`, `/provisioners`, `/metric-types`
- Association : `POST /providers/{provider_id}/provisioners/{provisioner_id}`
- Jobs manuels : `POST /providers/{id}/run`, `POST /provisioners/{id}/run`, `POST /applications/{id}/sync`
- Sync applications : `POST /applications/sync-due`
- Métriques : `GET /metrics/cpu`, `GET /metrics/ram`, `GET /metrics/disk`

## Observabilité

Prometheus peut scraper :

- API FastAPI : `http://localhost:8000/metrics`
- Worker Celery : `http://localhost:9101/metrics`
- Beat Celery : `http://beat:9101/metrics` depuis le réseau Docker
- Flower : `http://flower:5555/metrics` depuis le réseau Docker

Flower fournit la vue opérationnelle Celery :

- état des workers
- historique et état des tâches
- files, tâches en attente et tâches planifiées
- actions de contrôle à distance Celery

Grafana charge automatiquement un dashboard `Celery Monitoring` avec :

- throughput des tâches par état
- percentiles de durée des tâches
- nombre de tâches en cours
- statut du worker
- statut de Beat
- santé des cibles scrapées par Prometheus

Métriques principales :

- `api_http_requests_total`
- `api_http_request_duration_seconds`
- `celery_tasks_total`
- `celery_task_duration_seconds`
- `celery_tasks_in_progress`
- `celery_worker_up`
- `celery_beat_up`

Le endpoint Prometheus `/metrics` ne remplace pas les endpoints métier `/metrics/cpu`, `/metrics/ram` et `/metrics/disk`.

Accès par défaut :

- Flower utilise l'authentification HTTP Basic définie via `FLOWER_BASIC_AUTH`
- Grafana utilise `GRAFANA_ADMIN_USER` et `GRAFANA_ADMIN_PASSWORD`
- Prometheus n'est accessible que depuis les autres containers du compose, sauf publication explicite d'un port

## Métriques Machines

Les métriques sont stockées à la journée, avec une seule ligne par machine, provider, jour et variante de mesure :

- `machine_cpu_metrics` : valeur journalière de percentile CPU, avec la colonne `percentile`.
- `machine_ram_metrics` : valeur journalière de percentile RAM, avec la colonne `percentile`.
- `machine_disk_metrics` : valeur journalière d'usage disque, avec la colonne `usage_type`.

Les endpoints `/metrics/cpu`, `/metrics/ram` et `/metrics/disk` filtrent avec `start` et `end` au format date (`YYYY-MM-DD`). Les collectes font un upsert journalier : relancer une collecte le même jour met à jour la ligne existante.

## Applications

La table `applications` contient une ligne par application, environnement et région. Les machines peuvent référencer cette table via `application_id`.

Chaque application doit être synchronisée au moins une fois tous les 5 jours. Celery Beat déclenche un dispatcher dédié qui sélectionne seulement un petit lot d'applications dues à chaque tick, afin d'étaler la charge au lieu de tout synchroniser en une fois.

Variables utiles :

- `APPLICATION_SYNC_TICK_SECONDS` : fréquence du dispatcher de sync applications.
- `APPLICATION_SYNC_WINDOW_DAYS` : fenêtre maximale entre deux synchronisations, par défaut 5 jours.
- `APPLICATION_SYNC_BATCH_SIZE` : si `0`, le batch est calculé automatiquement pour étaler toutes les applications sur la fenêtre.
- `APPLICATION_SYNC_RETRY_AFTER_SECONDS` : délai avant de replanifier une ligne déjà programmée mais pas encore synchronisée.

## Connecteurs MVP

Deux connecteurs stub sont disponibles :

- `mock_inventory` pour découvrir des machines
- `mock_metric` pour générer des samples CPU/RAM/Disk

Exemple de config provisioner :

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

Exemple de config provider :

```json
{
  "value": 42,
  "unit": "percent",
  "percentile": 95
}
```

## Développement

```bash
uv sync --group dev
uv run pytest
```

Pour appliquer les migrations contre Postgres :

```bash
uv run alembic upgrade head
```

Lancer les runtimes manuellement :

```bash
uv run uvicorn app.api.main:app --reload
uv run celery -A app.worker.celery.celery_app worker --loglevel=INFO --pool=solo
uv run celery -A app.beat.celery.celery_app beat --loglevel=INFO
uv run celery -A app.worker.celery.celery_app flower
```
