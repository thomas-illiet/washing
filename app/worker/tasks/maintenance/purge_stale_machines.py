"""Worker task that deletes stale machine rows."""

from app.worker.tasks._db import run_with_db_session
from internal.infra.config.settings import get_settings
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import PURGE_STALE_MACHINES_TASK
from internal.usecases.maintenance import purge_stale_machines


@celery_app.task(name=PURGE_STALE_MACHINES_TASK)
def purge_stale_machines_task() -> dict[str, int | str]:
    """Delete machines older than the configured retention window."""
    retention_days = get_settings().machine_retention_days
    return run_with_db_session(lambda db: purge_stale_machines(db, retention_days=retention_days))
