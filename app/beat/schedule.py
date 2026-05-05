"""Celery Beat schedule builder."""

from internal.infra.config.settings import get_settings
from internal.infra.queue.task_names import DISPATCH_DUE_APPLICATION_SYNCS_TASK, DISPATCH_DUE_JOBS_TASK


def build_beat_schedule() -> dict[str, dict[str, str | int]]:
    """Build the Beat schedule from application settings."""
    settings = get_settings()
    return {
        "dispatch-due-jobs": {
            "task": DISPATCH_DUE_JOBS_TASK,
            "schedule": settings.scheduler_tick_seconds,
        },
        "dispatch-due-application-syncs": {
            "task": DISPATCH_DUE_APPLICATION_SYNCS_TASK,
            "schedule": settings.application_sync_tick_seconds,
        },
    }
