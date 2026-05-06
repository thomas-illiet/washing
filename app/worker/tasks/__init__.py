"""Worker task registry grouped by business domain."""

from app.worker.tasks.applications import (
    sync_application_inventory_discovery_task,
    sync_application_metrics_task,
)
from app.worker.tasks.inventory import run_provisioner_task
from app.worker.tasks.maintenance import purge_old_task_executions_task
from app.worker.tasks.maintenance import purge_stale_applications_task
from app.worker.tasks.maintenance import purge_stale_machines_task
from app.worker.tasks.metrics import (
    dispatch_enabled_provider_syncs_task,
    run_provider_machine_task,
    run_provider_task,
)
from app.worker.tasks.scheduler import (
    dispatch_due_application_metrics_syncs_task,
    dispatch_due_machine_provisioner_jobs_task,
)

__all__ = [
    "dispatch_enabled_provider_syncs_task",
    "dispatch_due_application_metrics_syncs_task",
    "dispatch_due_machine_provisioner_jobs_task",
    "purge_old_task_executions_task",
    "purge_stale_applications_task",
    "purge_stale_machines_task",
    "run_provider_machine_task",
    "run_provider_task",
    "run_provisioner_task",
    "sync_application_inventory_discovery_task",
    "sync_application_metrics_task",
]
