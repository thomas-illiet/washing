"""Worker task that runs one application metrics sync."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RUN_PROVIDER_MACHINE_TASK, SYNC_APPLICATION_METRICS_TASK
from internal.usecases.applications import run_application_metrics_sync

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=SYNC_APPLICATION_METRICS_TASK)
def sync_application_metrics_task(application_id: int) -> dict[str, int | str]:
    """Execute one application metrics sync."""
    return run_with_db_session(
        lambda db: run_application_metrics_sync(
            db,
            application_id,
            enqueue_machine_sync=lambda provider_id, machine_id: enqueue_celery_task(
                RUN_PROVIDER_MACHINE_TASK,
                args=[provider_id, machine_id],
            ).id,
        )
    )
