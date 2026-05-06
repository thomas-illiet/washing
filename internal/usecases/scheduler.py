"""Scheduling helpers for provisioner dispatch."""

from collections.abc import Callable
from datetime import datetime

from croniter import croniter
from sqlalchemy.orm import Session

from internal.infra.db.base import utcnow
from internal.infra.db.models import MachineProvisioner


def is_due(cron: str, last_scheduled_at: datetime | None, now: datetime | None = None) -> bool:
    """Return whether a provisioner should be scheduled at the given time."""
    now = now or utcnow()
    if last_scheduled_at is None:
        return True
    next_due = croniter(cron, last_scheduled_at).get_next(datetime)
    if next_due.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif next_due.tzinfo is not None and now.tzinfo is None:
        next_due = next_due.replace(tzinfo=None)
    return next_due <= now


def dispatch_due_jobs(
    db: Session,
    enqueue_provisioner: Callable[[int], str],
    now: datetime | None = None,
) -> dict[str, list[int]]:
    """Enqueue every enabled provisioner whose cron is currently due."""
    now = now or utcnow()
    provisioners_query = db.query(MachineProvisioner).filter(MachineProvisioner.enabled.is_(True))
    if db.get_bind().dialect.name != "sqlite":
        # Reserve rows first so concurrent schedulers cannot double-dispatch the same cron slot.
        provisioners_query = provisioners_query.with_for_update(skip_locked=True)

    reserved: list[tuple[int, datetime | None]] = []
    for provisioner in provisioners_query.all():
        if is_due(provisioner.cron, provisioner.last_scheduled_at, now):
            reserved.append((provisioner.id, provisioner.last_scheduled_at))
            provisioner.last_scheduled_at = now

    # Commit the reservation before enqueueing so later readers see the slot as taken.
    db.commit()

    enqueued_provisioners: list[int] = []
    try:
        for provisioner_id, _previous_last_scheduled_at in reserved:
            enqueue_provisioner(provisioner_id)
            enqueued_provisioners.append(provisioner_id)
    except Exception:
        for provisioner_id, previous_last_scheduled_at in reserved[len(enqueued_provisioners):]:
            provisioner = db.get(MachineProvisioner, provisioner_id)
            if provisioner is not None:
                # Restore only the rows whose publish never happened.
                provisioner.last_scheduled_at = previous_last_scheduled_at
        db.commit()
        raise

    return {"provisioners": enqueued_provisioners}
