"""Maintenance use cases for housekeeping tasks."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from internal.infra.db.base import utcnow
from internal.infra.db.models import Application, CeleryTaskExecution, Machine


def purge_old_task_executions(
    db: Session,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, int | str]:
    """Delete tracked Celery executions older than the configured retention window."""
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days)
    deleted = (
        db.query(CeleryTaskExecution)
        .filter(CeleryTaskExecution.queued_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {
        "deleted": int(deleted),
        "retention_days": retention_days,
        "status": "completed",
    }


def purge_stale_machines(
    db: Session,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, int | str]:
    """Delete machines whose last update is older than the configured retention window."""
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days)
    deleted = db.query(Machine).filter(Machine.updated_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted": int(deleted),
        "status": "completed",
    }


def purge_stale_applications(
    db: Session,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, int | str]:
    """Delete applications whose last update is older than the configured retention window."""
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days)
    deleted = db.query(Application).filter(Application.updated_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted": int(deleted),
        "status": "completed",
    }
