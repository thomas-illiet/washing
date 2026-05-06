"""Worker task that runs one provider/machine metric collection."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVIDER_MACHINE_TASK
from internal.usecases.metrics import run_provider_machine_collection

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=RUN_PROVIDER_MACHINE_TASK)
def run_provider_machine_task(provider_id: int, machine_id: int) -> dict[str, int | str]:
    """Execute one provider collection for a single machine."""
    return run_with_db_session(lambda db: run_provider_machine_collection(db, provider_id, machine_id))
