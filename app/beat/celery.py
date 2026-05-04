"""Beat entrypoint for Celery."""

from app.beat.schedule import build_beat_schedule
from internal.infra.queue.celery import celery_app


celery_app.conf.beat_schedule = build_beat_schedule()

__all__ = ["celery_app"]
