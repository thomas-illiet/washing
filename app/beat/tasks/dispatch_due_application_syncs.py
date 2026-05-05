"""Beat task that dispatches due application sync jobs."""

from internal.infra.config.settings import get_settings
from internal.infra.db.session import SessionLocal
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import DISPATCH_DUE_APPLICATION_SYNCS_TASK, SYNC_APPLICATION_TASK
from internal.usecases.applications import dispatch_due_application_syncs


@celery_app.task(name=DISPATCH_DUE_APPLICATION_SYNCS_TASK)
def dispatch_due_application_syncs_task() -> dict[str, list[int] | int]:
    """Celery entrypoint that schedules due application sync work."""
    settings = get_settings()
    db = SessionLocal()
    try:
        return dispatch_due_application_syncs(
            db,
            enqueue_application=lambda application_id: celery_app.send_task(SYNC_APPLICATION_TASK, args=[application_id]).id,
            window_days=settings.application_sync_window_days,
            tick_seconds=settings.application_sync_tick_seconds,
            configured_batch_size=settings.application_sync_batch_size,
            retry_after_seconds=settings.application_sync_retry_after_seconds,
        )
    finally:
        db.close()
