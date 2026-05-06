"""Celery Beat schedule builder."""

from internal.infra.config.settings import get_settings
from internal.infra.queue.task_names import (
    DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
    DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK,
    SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
)


def build_beat_schedule() -> dict[str, dict[str, str | int]]:
    """Build the Beat schedule from application settings."""
    settings = get_settings()
    return {
        "dispatch-due-machine-provisioner-jobs": {
            "task": DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK,
            "schedule": settings.scheduler_tick_seconds,
        },
        "sync-application-inventory-discovery": {
            "task": SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
            "schedule": settings.application_inventory_sync_tick_seconds,
        },
        "dispatch-due-application-metrics-syncs": {
            "task": DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
            "schedule": settings.application_metrics_sync_tick_seconds,
        },
    }
