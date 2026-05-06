"""Beat entrypoint for Celery."""

from celery.beat import Scheduler

from app.beat.schedule import build_beat_schedule
from internal.infra.queue.celery import celery_app


celery_app.conf.beat_schedule = build_beat_schedule()
celery_app.conf.beat_scheduler = f"{Scheduler.__module__}:{Scheduler.__qualname__}"

__all__ = ["celery_app"]
