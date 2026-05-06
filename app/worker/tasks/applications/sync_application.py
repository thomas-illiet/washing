"""Worker task that runs one application sync."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import SYNC_APPLICATION_TASK
from internal.usecases.applications import run_application_sync

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=SYNC_APPLICATION_TASK)
def sync_application_task(application_id: int) -> dict[str, int]:
    """Execute one application sync."""
    return run_with_db_session(lambda db: run_application_sync(db, application_id))
