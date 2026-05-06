"""Tests covering Celery Beat configuration."""

from celery.schedules import crontab

from app.beat.celery import celery_app
from app.beat.schedule import build_beat_schedule
from internal.infra.queue.task_names import (
    PURGE_OLD_TASK_EXECUTIONS_TASK,
    PURGE_STALE_APPLICATIONS_TASK,
    PURGE_STALE_MACHINES_TASK,
)


def test_beat_uses_in_memory_scheduler() -> None:
    """Ensure Beat always uses the in-memory scheduler."""
    assert celery_app.conf.beat_scheduler == "celery.beat:Scheduler"


def test_beat_loads_expected_schedule() -> None:
    """Ensure Beat keeps using the application schedule builder."""
    assert celery_app.conf.beat_schedule == build_beat_schedule()


def test_beat_schedules_application_metric_syncs() -> None:
    """Application metrics syncs should be scheduled from Beat."""
    assert "dispatch-due-application-metrics-syncs" in build_beat_schedule()


def test_beat_schedules_daily_task_history_cleanup() -> None:
    """Old Celery task history should be purged once per day."""
    schedule = build_beat_schedule()["purge-old-task-executions"]
    assert schedule["task"] == PURGE_OLD_TASK_EXECUTIONS_TASK
    assert schedule["schedule"] == crontab(minute=0, hour=3)


def test_beat_schedules_daily_stale_machine_cleanup() -> None:
    """Stale machine inventory should be purged once per day."""
    schedule = build_beat_schedule()["purge-stale-machines"]
    assert schedule["task"] == PURGE_STALE_MACHINES_TASK
    assert schedule["schedule"] == crontab(minute=30, hour=3)


def test_beat_schedules_daily_stale_application_cleanup() -> None:
    """Stale applications should be purged once per day."""
    schedule = build_beat_schedule()["purge-stale-applications"]
    assert schedule["task"] == PURGE_STALE_APPLICATIONS_TASK
    assert schedule["schedule"] == crontab(minute=0, hour=4)
