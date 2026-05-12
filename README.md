# Metrics Collector

Backend Python pour collecter l’inventaire machine et les métriques depuis des produits externes.

Le projet expose :

- une API FastAPI pour administrer les plateformes, connecteurs et synchronisations
- une passerelle MCP read-only au-dessus de l’API
- des workers Celery pour les collectes et les fan-out de tâches
- un scheduler Beat pour les traitements périodiques
- une stack locale avec Postgres, Redis, Keycloak, Flower, Prometheus et Grafana

## Démarrage rapide

1. Crée les fichiers locaux à partir des templates.

```bash
cp Dockerfile.example Dockerfile
cp .env.example .env
cp docker-compose.example.yml docker-compose.yml
```

2. Génère une clé Fernet pour chiffrer la config des connecteurs.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

3. Mets cette valeur dans `INTEGRATION_CONFIG_ENCRYPTION_KEY` dans `.env`.

4. Démarre la base et Redis.

```bash
docker compose up --build -d db redis
```

5. Applique les migrations.

```bash
docker compose run --rm migrate
```

6. Démarre le reste de la stack.

```bash
docker compose up -d api mcp worker beat flower prometheus grafana
```

La stack locale démarre aussi Keycloak et importe automatiquement le realm `washing-machine` depuis [config/keycloak/washing-machine-realm.json](/Users/thomas-illiet/Documents/New%20project%202/config/keycloak/washing-machine-realm.json).
Le Postgres local utilise une seule base `washing_machine`, avec le schéma `app` pour l’application et `keycloak` pour Keycloak.

## URLs utiles

- API : `http://localhost:8000`
- Swagger : `http://localhost:8000/`
- MCP : `http://localhost:8001/mcp`
- MCP health : `http://localhost:8001/health`
- Keycloak : `http://localhost:8080`
- Flower : `http://localhost:5555`
- Grafana : `http://localhost:3000`

Grafana provisionne deux dashboards par défaut : `Celery Monitoring` sur Prometheus et `Product KPI Overview` sur Postgres.

## Comptes locaux par défaut

- `reader` : `Read Only`, `reader@washing-machine.local`, reçoit le rôle `OIDC_USER_ROLE_NAME`
- `platform-admin` : `Platform Admin`, `platform-admin@washing-machine.local`, reçoit `OIDC_USER_ROLE_NAME` et `OIDC_ADMIN_ROLE_NAME`

Les usernames, prénoms, noms et emails sont définis dans l’import Keycloak local. Les mots de passe viennent de `.env`.

## Ce qu’il faut savoir

- L’auth supporte tout provider OIDC compatible discovery/JWKS, pas seulement Keycloak.
- Les noms de rôles sont configurables via `OIDC_USER_ROLE_NAME` et `OIDC_ADMIN_ROLE_NAME`.
- L’auth valide la signature, l’issuer, `exp` et `nbf`.
- L’audience est volontairement ignorée.
- `/health` reste public sur l’API et le MCP.
- `/metrics` reste public côté API pour Prometheus.
- `APP_ENV=dev` expose les routes mock dans Swagger.
- Les connecteurs placeholder peuvent être valides et retourner zéro donnée sans erreur.
- La table `applications` est une projection dérivée de `machines`, pas la source de vérité.
- L’historique `celery_task_executions` est purgé automatiquement tous les jours selon `CELERY_TASK_EXECUTION_RETENTION_DAYS`.
- L’inventaire `machines` est purgé automatiquement tous les jours selon `MACHINE_RETENTION_DAYS`.
- La projection `applications` est purgée séparément tous les jours selon `APPLICATION_RETENTION_DAYS`, sans toucher aux autres tables.

## Vérifications rapides

Après le démarrage, tu peux vérifier :

- `GET /health` retourne `200`
- `GET /` sert Swagger
- un token lecture peut appeler `GET /v1/platforms`
- un token lecture reçoit `403` sur `POST /v1/platforms`
- un token admin peut créer une plateforme
- `POST /mcp` sans token est refusé si `OIDC_ENABLED=true`

## Commandes utiles

Lancer les tests :

```bash
uv sync --dev
uv run pytest -q
```

Lancer les runtimes à la main :

```bash
uv run uvicorn app.api.main:app --reload
MCP_PRODUCT_API_BASE_URL=http://localhost:8000 uv run uvicorn app.mcp.main:app --reload --port 8001
uv run celery -A app.worker.celery.celery_app worker --loglevel=INFO --pool=solo
uv run celery -A app.beat.celery.celery_app beat --loglevel=INFO
uv run celery -A app.worker.celery.celery_app flower
```

Appliquer les migrations localement :

```bash
uv run alembic upgrade head
```

Suivre les logs Docker :

```bash
docker compose logs -f api mcp worker beat
```

Arrêter la stack :

```bash
docker compose down
```

Reset complet local :

```bash
docker compose down -v
```

## Vue rapide du projet

- `app/api` : API FastAPI
- `app/mcp` : gateway MCP read-only
- `app/worker` : worker Celery et tâches exécutables
- `app/beat` : scheduler Celery Beat
- `internal/usecases` : logique métier partagée
- `internal/domain` : règles pures de normalisation et validation
- `internal/infra` : DB, auth, queue, connecteurs, sécurité, observabilité
- `internal/contracts/http` : schémas HTTP
- `mock/` : presets JSON pour les mocks de dev

## Docs détaillées

Le `README` racine sert d’accueil. Pour le reste, va directement dans [docs/README.md](./docs/README.md).

- [Documentation index](./docs/README.md) : point d’entrée de la doc longue
- [Setup](./docs/setup.md) : installation locale, Docker, Python, tests, smoke checks
- [Configuration](./docs/configuration.md) : variables d’environnement, OIDC, scheduler, observability
- [Architecture](./docs/architecture.md) : runtimes, couches, flux métier, modèle de données
- [Machine Recommendations](./docs/recommendations.md) : calcul des recommandations, statuts, endpoints et exploitation
- [Deployment](./docs/deployment.md) : image, topologie, ordre de rollout, scaling, checklist
- [Operations](./docs/operations.md) : migrations, logs, maintenance, troubleshooting
- [Celery Task Map](./docs/celery-task-map.md) : cartographie des tâches, dispatchers et fan-out

## Pièges classiques

- Modifier le fichier de realm Keycloak ne met pas à jour un realm déjà importé.
- Le reset complet `docker compose down -v` efface à la fois les données applicatives et celles de Keycloak, car elles partagent maintenant la même base Postgres.
- Changer `INTEGRATION_CONFIG_ENCRYPTION_KEY` casse la lecture des configs déjà stockées si tu ne migres pas les données.
- Plusieurs instances `beat` compliquent l’exploitation, même si les dispatchers réservent maintenant les lignes correctement.
- Les fichiers `Dockerfile` et `docker-compose.yml` réels ne sont pas versionnés : le repo fournit les `*.example`.
