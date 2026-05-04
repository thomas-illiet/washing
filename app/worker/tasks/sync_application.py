from internal.infra.db.session import SessionLocal
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import SYNC_APPLICATION_TASK
from internal.usecases.applications import run_application_sync


@celery_app.task(name=SYNC_APPLICATION_TASK)
def sync_application_task(application_id: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        return run_application_sync(db, application_id)
    finally:
        db.close()
