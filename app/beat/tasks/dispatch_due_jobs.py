"""Beat task that dispatches due provisioner jobs."""

from internal.infra.db.session import SessionLocal
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import DISPATCH_DUE_JOBS_TASK, RUN_PROVISIONER_TASK
from internal.usecases.scheduler import dispatch_due_jobs


@celery_app.task(name=DISPATCH_DUE_JOBS_TASK)
def dispatch_due_jobs_task() -> dict[str, list[int]]:
    """Celery entrypoint that dispatches due provisioner jobs."""
    db = SessionLocal()
    try:
        return dispatch_due_jobs(
            db,
            enqueue_provisioner=lambda provisioner_id: celery_app.send_task(RUN_PROVISIONER_TASK, args=[provisioner_id]).id,
        )
    finally:
        db.close()
