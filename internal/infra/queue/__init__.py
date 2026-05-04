"""Queue and task dispatch infrastructure."""

from internal.infra.queue.celery import celery_app

__all__ = ["celery_app"]
