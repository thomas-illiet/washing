"""Tests covering Celery worker task registration."""

from app.worker.celery import celery_app
from internal.infra.queue.task_names import (
    DISPATCH_DUE_APPLICATION_SYNCS_TASK,
    DISPATCH_DUE_JOBS_TASK,
    RUN_PROVIDER_TASK,
    RUN_PROVISIONER_TASK,
    SYNC_APPLICATION_TASK,
)


def test_worker_registers_execution_and_dispatch_tasks() -> None:
    """Worker startup should register both scheduler and execution tasks."""
    registered_tasks = celery_app.tasks.keys()
    for task_name in [
        DISPATCH_DUE_APPLICATION_SYNCS_TASK,
        DISPATCH_DUE_JOBS_TASK,
        RUN_PROVIDER_TASK,
        RUN_PROVISIONER_TASK,
        SYNC_APPLICATION_TASK,
    ]:
        assert task_name in registered_tasks
