"""Worker task that deletes old tracked Celery execution rows."""

from app.worker.tasks._db import run_with_db_session
from internal.infra.config.settings import get_settings
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import PURGE_OLD_TASK_EXECUTIONS_TASK
from internal.usecases.maintenance import purge_old_task_executions


@celery_app.task(name=PURGE_OLD_TASK_EXECUTIONS_TASK)
def purge_old_task_executions_task() -> dict[str, int | str]:
    """Delete persisted task history older than the configured retention window."""
    retention_days = get_settings().celery_task_execution_retention_days
    return run_with_db_session(lambda db: purge_old_task_executions(db, retention_days=retention_days))
