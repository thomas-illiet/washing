from datetime import datetime, timedelta
from math import ceil
from typing import Callable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from internal.infra.db.base import utcnow
from internal.infra.db.models import Application


def calculate_application_sync_batch_size(
    total_applications: int,
    window_days: int,
    tick_seconds: int,
    configured_batch_size: int = 0,
) -> int:
    if total_applications <= 0:
        return 0
    if configured_batch_size > 0:
        return configured_batch_size

    window_seconds = max(1, window_days * 24 * 60 * 60)
    ticks_per_window = max(1, window_seconds // max(1, tick_seconds))
    return max(1, ceil(total_applications / ticks_per_window))


def dispatch_due_application_syncs(
    db: Session,
    enqueue_application: Callable[[int], str],
    now: datetime | None = None,
    window_days: int = 5,
    tick_seconds: int = 3600,
    configured_batch_size: int = 0,
    retry_after_seconds: int = 3600,
) -> dict[str, list[int] | int]:
    now = now or utcnow()
    total_applications = db.query(func.count(Application.id)).scalar() or 0
    batch_size = calculate_application_sync_batch_size(
        total_applications=total_applications,
        window_days=window_days,
        tick_seconds=tick_seconds,
        configured_batch_size=configured_batch_size,
    )
    if batch_size == 0:
        return {"applications": [], "batch_size": 0}

    due_before = now - timedelta(days=window_days)
    retry_before = now - timedelta(seconds=retry_after_seconds)
    due_applications = (
        db.query(Application)
        .filter(or_(Application.sync_at.is_(None), Application.sync_at <= due_before))
        .filter(or_(Application.sync_scheduled_at.is_(None), Application.sync_scheduled_at <= retry_before))
        .order_by(Application.sync_at.asc().nullsfirst(), Application.id.asc())
        .limit(batch_size)
        .all()
    )

    application_ids: list[int] = []
    for application in due_applications:
        enqueue_application(application.id)
        application.sync_scheduled_at = now
        application_ids.append(application.id)

    db.commit()
    return {"applications": application_ids, "batch_size": batch_size}


def run_application_sync(db: Session, application_id: int) -> dict[str, int]:
    application = db.get(Application, application_id)
    if application is None:
        raise ValueError(f"application {application_id} not found")

    now = utcnow()
    try:
        application.sync_at = now
        application.sync_scheduled_at = None
        application.sync_error = None
        application.extra = {
            **(application.extra or {}),
            "last_sync": {
                "status": "success",
                "synced_at": now.isoformat(),
            },
        }
        db.commit()
        return {"synced": 1}
    except Exception as exc:
        db.rollback()
        application = db.get(Application, application_id)
        if application is not None:
            application.sync_error = str(exc)
            db.commit()
        raise
