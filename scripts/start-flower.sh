#!/bin/sh
set -eu

fallback_db=".data/flower/flower.db"
requested_db="${FLOWER_DB:-$fallback_db}"
requested_dir="$(dirname "$requested_db")"

if mkdir -p "$requested_dir" 2>/dev/null && [ -w "$requested_dir" ]; then
  export FLOWER_DB="$requested_db"
else
  fallback_dir="$(dirname "$fallback_db")"
  mkdir -p "$fallback_dir"
  export FLOWER_DB="$fallback_db"
  echo "FLOWER_DB=$requested_db n'est pas accessible en ecriture, utilisation de $FLOWER_DB" >&2
fi

exec uv run celery -A app.worker.celery.celery_app flower
