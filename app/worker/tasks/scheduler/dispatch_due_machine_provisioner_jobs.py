"""Worker task that dispatches due machine provisioner jobs."""

from internal.infra.queue.celery import celery_app
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import (
    DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK,
    RUN_PROVISIONER_TASK,
)
from internal.usecases.scheduler import dispatch_due_jobs

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK)
def dispatch_due_machine_provisioner_jobs_task() -> dict[str, list[int]]:
    """Enqueue every due machine provisioner execution task."""
    return run_with_db_session(
        lambda db: dispatch_due_jobs(
            db,
            enqueue_provisioner=lambda provisioner_id: enqueue_celery_task(RUN_PROVISIONER_TASK, args=[provisioner_id]).id,
        )
    )
