from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.applications import run_application_sync


@celery_app.task(name="applications.sync")
def sync_application_task(application_id: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        return run_application_sync(db, application_id)
    finally:
        db.close()
