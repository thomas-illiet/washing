from collections.abc import Callable
from datetime import datetime

from croniter import croniter
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import MachineProvider, MachineProvisioner


def is_due(cron: str, last_scheduled_at: datetime | None, now: datetime | None = None) -> bool:
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
    enqueue_provider: Callable[[int], str],
    enqueue_provisioner: Callable[[int], str],
    now: datetime | None = None,
) -> dict[str, list[int]]:
    now = now or utcnow()
    provider_ids: list[int] = []
    provisioner_ids: list[int] = []

    for provisioner in db.query(MachineProvisioner).filter(MachineProvisioner.enabled.is_(True)).all():
        if is_due(provisioner.cron, provisioner.last_scheduled_at, now):
            enqueue_provisioner(provisioner.id)
            provisioner.last_scheduled_at = now
            provisioner_ids.append(provisioner.id)

    for provider in db.query(MachineProvider).filter(MachineProvider.enabled.is_(True)).all():
        if is_due(provider.cron, provider.last_scheduled_at, now):
            enqueue_provider(provider.id)
            provider.last_scheduled_at = now
            provider_ids.append(provider.id)

    db.commit()
    return {"providers": provider_ids, "provisioners": provisioner_ids}
