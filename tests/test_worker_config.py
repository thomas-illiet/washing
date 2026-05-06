"""Tests covering Celery worker task registration."""

from app.worker.celery import celery_app
from internal.infra.queue.task_names import (
    DISPATCH_ENABLED_PROVIDER_SYNCS_TASK,
    DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
    DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK,
    PURGE_OLD_TASK_EXECUTIONS_TASK,
    PURGE_STALE_APPLICATIONS_TASK,
    PURGE_STALE_MACHINES_TASK,
    RUN_PROVIDER_MACHINE_TASK,
    RUN_PROVIDER_TASK,
    RUN_PROVISIONER_TASK,
    SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
    SYNC_APPLICATION_METRICS_TASK,
)


def test_worker_registers_execution_and_dispatch_tasks() -> None:
    """Worker startup should register both scheduler and execution tasks."""
    registered_tasks = celery_app.tasks.keys()
    for task_name in [
        DISPATCH_ENABLED_PROVIDER_SYNCS_TASK,
        DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
        DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK,
        PURGE_OLD_TASK_EXECUTIONS_TASK,
        PURGE_STALE_APPLICATIONS_TASK,
        PURGE_STALE_MACHINES_TASK,
        RUN_PROVIDER_MACHINE_TASK,
        RUN_PROVIDER_TASK,
        RUN_PROVISIONER_TASK,
        SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
        SYNC_APPLICATION_METRICS_TASK,
    ]:
        assert task_name in registered_tasks
