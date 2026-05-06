"""Worker task that dispatches due application metrics sync jobs."""

from internal.infra.config.settings import get_settings
from internal.infra.queue.celery import celery_app
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import (
    DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
    SYNC_APPLICATION_METRICS_TASK,
)
from internal.usecases.applications import dispatch_due_application_metrics_syncs

from app.worker.tasks._db import run_with_db_session


@celery_app.task(name=DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK)
def dispatch_due_application_metrics_syncs_task() -> dict[str, list[int] | int]:
    """Enqueue the next batch of due application metrics sync tasks."""
    settings = get_settings()
    return run_with_db_session(
        lambda db: dispatch_due_application_metrics_syncs(
            db,
            enqueue_application=lambda application_id: enqueue_celery_task(
                SYNC_APPLICATION_METRICS_TASK,
                args=[application_id],
            ).id,
            window_days=settings.application_metrics_sync_window_days,
            tick_seconds=settings.application_metrics_sync_tick_seconds,
            configured_batch_size=settings.application_metrics_sync_batch_size,
            retry_after_seconds=settings.application_metrics_sync_retry_after_seconds,
        )
    )
