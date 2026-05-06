"""Maintenance worker tasks."""

from app.worker.tasks.maintenance.purge_old_task_executions import purge_old_task_executions_task
from app.worker.tasks.maintenance.purge_stale_applications import purge_stale_applications_task
from app.worker.tasks.maintenance.purge_stale_machines import purge_stale_machines_task

__all__ = [
    "purge_old_task_executions_task",
    "purge_stale_applications_task",
    "purge_stale_machines_task",
]
