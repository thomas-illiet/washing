"""Worker task that dispatches machine-level provider collections."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RUN_PROVIDER_MACHINE_TASK, RUN_PROVIDER_TASK
from internal.usecases.metrics import dispatch_provider_machine_syncs

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=RUN_PROVIDER_TASK)
def run_provider_task(provider_id: int) -> dict[str, int | list[int] | str]:
    """Enqueue one machine-level metric collection task per visible machine."""
    return run_with_db_session(
        lambda db: dispatch_provider_machine_syncs(
            db,
            provider_id,
            enqueue_machine_sync=lambda task_provider_id, machine_id: enqueue_celery_task(
                RUN_PROVIDER_MACHINE_TASK,
                args=[task_provider_id, machine_id],
            ).id,
        )
    )
