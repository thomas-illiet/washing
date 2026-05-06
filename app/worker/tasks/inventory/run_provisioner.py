"""Worker task that runs one provisioner inventory sync."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVISIONER_TASK
from internal.usecases.inventory import run_provisioner_inventory

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=RUN_PROVISIONER_TASK)
def run_provisioner_task(provisioner_id: int) -> dict[str, int]:
    """Execute one provisioner inventory sync."""
    return run_with_db_session(lambda db: run_provisioner_inventory(db, provisioner_id))
