"""Worker task that runs one provider collection."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVIDER_TASK
from internal.usecases.metrics import run_provider_collection

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=RUN_PROVIDER_TASK)
def run_provider_task(provider_id: int) -> dict[str, int]:
    """Execute one provider collection."""
    return run_with_db_session(lambda db: run_provider_collection(db, provider_id))
