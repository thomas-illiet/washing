from celery import Celery

from app.core.config import get_settings
from app.core.prometheus import configure_celery_prometheus


settings = get_settings()

celery_app = Celery(
    "metrics_collector",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "dispatch-due-jobs": {
            "task": "scheduler.dispatch_due_jobs",
            "schedule": settings.scheduler_tick_seconds,
        },
        "dispatch-due-application-syncs": {
            "task": "applications.dispatch_due_syncs",
            "schedule": settings.application_sync_tick_seconds,
        },
    },
)

configure_celery_prometheus()

import app.tasks  # noqa: E402,F401
