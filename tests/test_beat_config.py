"""Tests covering Celery Beat configuration."""

from app.beat.celery import celery_app
from app.beat.schedule import build_beat_schedule


def test_beat_uses_in_memory_scheduler() -> None:
    """Ensure Beat always uses the in-memory scheduler."""
    assert celery_app.conf.beat_scheduler == "celery.beat:Scheduler"


def test_beat_loads_expected_schedule() -> None:
    """Ensure Beat keeps using the application schedule builder."""
    assert celery_app.conf.beat_schedule == build_beat_schedule()
