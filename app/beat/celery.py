"""Beat entrypoint for Celery."""

from app.beat.schedule import build_beat_schedule
from internal.infra.config.settings import get_settings
from internal.infra.queue.celery import celery_app


settings = get_settings()

celery_app.conf.beat_schedule = build_beat_schedule()
celery_app.conf.beat_schedule_filename = settings.celery_beat_schedule_path

__all__ = ["celery_app"]
