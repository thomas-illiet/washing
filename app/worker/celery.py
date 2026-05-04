"""Worker entrypoint for Celery."""

import app.beat.tasks  # noqa: F401
import app.worker.tasks  # noqa: F401
from internal.infra.queue.celery import celery_app

__all__ = ["celery_app"]
