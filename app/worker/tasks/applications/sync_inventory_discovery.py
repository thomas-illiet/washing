"""Worker task that rebuilds applications from machine inventory."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK
from internal.usecases.applications import rebuild_applications_from_machines

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK)
def sync_application_inventory_discovery_task() -> dict[str, int]:
    """Execute the global inventory-discovery rebuild."""
    return run_with_db_session(rebuild_applications_from_machines)
