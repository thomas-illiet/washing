"""Worker task that runs one provisioner inventory sync."""

from internal.infra.db.session import SessionLocal
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVISIONER_TASK
from internal.usecases.inventory import run_provisioner_inventory


@celery_app.task(name=RUN_PROVISIONER_TASK)
def run_provisioner_task(provisioner_id: int) -> dict[str, int]:
    """Execute provisioner inventory discovery inside a DB session."""
    db = SessionLocal()
    try:
        return run_provisioner_inventory(db, provisioner_id)
    finally:
        db.close()
