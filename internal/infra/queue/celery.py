"""Shared Celery application configuration."""

from celery import Celery

from internal.infra.config.settings import get_settings
from internal.infra.observability.prometheus import configure_celery_prometheus
from internal.infra.queue.task_tracking import configure_celery_task_tracking


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
)

configure_celery_prometheus()
configure_celery_task_tracking()
