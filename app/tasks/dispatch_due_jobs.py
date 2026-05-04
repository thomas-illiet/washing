from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.scheduler import dispatch_due_jobs
from app.tasks.run_provider import run_provider_task
from app.tasks.run_provisioner import run_provisioner_task


@celery_app.task(name="scheduler.dispatch_due_jobs")
def dispatch_due_jobs_task() -> dict[str, list[int]]:
    db = SessionLocal()
    try:
        return dispatch_due_jobs(
            db,
            enqueue_provider=lambda provider_id: run_provider_task.delay(provider_id).id,
            enqueue_provisioner=lambda provisioner_id: run_provisioner_task.delay(provisioner_id).id,
        )
    finally:
        db.close()
