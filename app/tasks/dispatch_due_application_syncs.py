from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.applications import dispatch_due_application_syncs
from app.tasks.sync_application import sync_application_task


@celery_app.task(name="applications.dispatch_due_syncs")
def dispatch_due_application_syncs_task() -> dict[str, list[int] | int]:
    settings = get_settings()
    db = SessionLocal()
    try:
        return dispatch_due_application_syncs(
            db,
            enqueue_application=lambda application_id: sync_application_task.delay(application_id).id,
            window_days=settings.application_sync_window_days,
            tick_seconds=settings.application_sync_tick_seconds,
            configured_batch_size=settings.application_sync_batch_size,
            retry_after_seconds=settings.application_sync_retry_after_seconds,
        )
    finally:
        db.close()
