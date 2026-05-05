"""Helpers for sending tracked Celery tasks."""

from collections.abc import Sequence

from celery.result import AsyncResult

from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_tracking import build_task_tracking_headers


def enqueue_celery_task(
    task_name: str,
    args: Sequence[object] | None = None,
    kwargs: dict[str, object] | None = None,
) -> AsyncResult:
    """Send a Celery task with tracking headers attached."""
    task_args = list(args or [])
    task_kwargs = kwargs or {}
    headers = build_task_tracking_headers(task_name, task_args)
    return celery_app.send_task(task_name, args=task_args, kwargs=task_kwargs, headers=headers)
