"""Application synchronization use cases."""

from datetime import datetime, timedelta
from math import ceil
from typing import Callable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from internal.domain import coalesce_dimension, normalize_application_code
from internal.infra.db.base import utcnow
from internal.infra.db.models import Application, Machine, MachineProvider


def calculate_application_metrics_sync_batch_size(
    total_applications: int,
    window_days: int,
    tick_seconds: int,
    configured_batch_size: int = 0,
) -> int:
    """Compute the number of applications to sync on each dispatcher tick."""
    if total_applications <= 0:
        return 0
    if configured_batch_size > 0:
        return configured_batch_size

    window_seconds = max(1, window_days * 24 * 60 * 60)
    ticks_per_window = max(1, window_seconds // max(1, tick_seconds))
    return max(1, ceil(total_applications / ticks_per_window))


def rebuild_applications_from_machines(db: Session) -> dict[str, int]:
    """Rebuild the applications projection from the current machine snapshot."""
    grouped_rows = (
        db.query(Machine.application, Machine.environment, Machine.region)
        .filter(Machine.application.is_not(None))
        .group_by(Machine.application, Machine.environment, Machine.region)
        .all()
    )
    snapshot = {
        (
            normalize_application_code(application),
            coalesce_dimension(environment),
            coalesce_dimension(region),
        )
        for application, environment, region in grouped_rows
        if normalize_application_code(application) is not None
    }
    snapshot.discard((None, "UNKNOWN", "UNKNOWN"))

    existing = db.query(Application).all()
    existing_by_key = {(item.name, item.environment, item.region): item for item in existing}

    created = 0
    for name, environment, region in sorted(snapshot):
        if (name, environment, region) in existing_by_key:
            continue
        db.add(Application(name=name, environment=environment, region=region))
        created += 1

    deleted = 0
    for key, application in existing_by_key.items():
        if key in snapshot:
            continue
        db.delete(application)
        deleted += 1

    db.commit()
    return {
        "created": created,
        "deleted": deleted,
        "total": len(snapshot),
    }


def dispatch_due_application_metrics_syncs(
    db: Session,
    enqueue_application: Callable[[int], str],
    now: datetime | None = None,
    window_days: int = 5,
    tick_seconds: int = 3600,
    configured_batch_size: int = 0,
    retry_after_seconds: int = 3600,
) -> dict[str, list[int] | int]:
    """Enqueue the next batch of due application sync jobs."""
    now = now or utcnow()
    total_applications = db.query(func.count(Application.id)).scalar() or 0
    batch_size = calculate_application_metrics_sync_batch_size(
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


def _application_machines(db: Session, application: Application) -> list[Machine]:
    """Return the current machines belonging to one application projection row."""
    return (
        db.query(Machine)
        .filter(Machine.application == application.name)
        .filter(func.coalesce(Machine.environment, "UNKNOWN") == application.environment)
        .filter(func.coalesce(Machine.region, "UNKNOWN") == application.region)
        .order_by(Machine.id.asc())
        .all()
    )


def _visible_enabled_providers(db: Session, platform_ids: set[int]) -> list[MachineProvider]:
    """Return enabled providers for the platforms represented in one application batch."""
    if not platform_ids:
        return []
    return (
        db.query(MachineProvider)
        .options(selectinload(MachineProvider.provisioners))
        .filter(MachineProvider.enabled.is_(True))
        .filter(MachineProvider.platform_id.in_(sorted(platform_ids)))
        .order_by(MachineProvider.id.asc())
        .all()
    )


def _provider_sees_machine(provider: MachineProvider, machine: Machine) -> bool:
    """Return whether one enabled provider can collect metrics for one machine."""
    if provider.platform_id != machine.platform_id:
        return False
    provisioner_ids = {provisioner.id for provisioner in provider.provisioners}
    if not provisioner_ids:
        return True
    return machine.source_provisioner_id in provisioner_ids


def run_application_metrics_sync(
    db: Session,
    application_id: int,
    enqueue_machine_sync: Callable[[int, int], str],
) -> dict[str, int | str]:
    """Dispatch one distributed metrics sync for a single application batch."""
    application = db.get(Application, application_id)
    if application is None:
        raise ValueError(f"application {application_id} not found")

    try:
        machines = _application_machines(db, application)
        providers = _visible_enabled_providers(db, {machine.platform_id for machine in machines})
        pairs = [
            (machine.id, provider.id)
            for machine in machines
            for provider in providers
            if _provider_sees_machine(provider, machine)
        ]

        for machine_id, provider_id in pairs:
            enqueue_machine_sync(provider_id, machine_id)

        now = utcnow()
        application.sync_scheduled_at = None
        application.sync_at = now
        application.sync_error = None
        application.extra = {
            **(application.extra or {}),
            "last_metrics_sync": {
                "status": "dispatched" if pairs else "noop",
                "updated_at": now.isoformat(),
                "machines": len(machines),
                "tasks": len(pairs),
            },
        }
        db.commit()
        return {
            "application_id": application.id,
            "machines": len(machines),
            "synced": len(pairs),
            "status": "dispatched" if pairs else "noop",
        }
    except Exception as exc:
        db.rollback()
        application = db.get(Application, application_id)
        if application is not None:
            application.sync_scheduled_at = None
            application.sync_error = str(exc)
            db.commit()
        raise
