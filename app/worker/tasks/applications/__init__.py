"""Worker tasks for application jobs."""

from app.worker.tasks.applications.sync_inventory_discovery import sync_application_inventory_discovery_task
from app.worker.tasks.applications.sync_metrics import sync_application_metrics_task

__all__ = [
    "sync_application_inventory_discovery_task",
    "sync_application_metrics_task",
]
