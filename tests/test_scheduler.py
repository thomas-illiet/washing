"""Tests covering scheduling use cases."""

from datetime import timedelta

from sqlalchemy.orm import Session

from internal.infra.db.base import utcnow
from internal.infra.db.models import Application, MachineProvisioner, Platform
from internal.usecases.applications import dispatch_due_application_metrics_syncs
from internal.usecases.scheduler import dispatch_due_jobs


def test_dispatch_due_jobs_enqueues_due_enabled_provisioners(db_session: Session) -> None:
    """The scheduler should only enqueue due enabled provisioners."""
    now = utcnow()
    platform = Platform(name="Scheduler")
    provisioner = MachineProvisioner(
        platform=platform,
        name="inventory",
        type="mock_inventory",
        enabled=True,
        cron="* * * * *",
        last_scheduled_at=now - timedelta(minutes=2),
    )
    db_session.add(provisioner)
    db_session.commit()

    enqueued_provisioners: list[int] = []
    result = dispatch_due_jobs(
        db_session,
        enqueue_provisioner=lambda provisioner_id: enqueued_provisioners.append(provisioner_id) or "task-provisioner",
        now=now,
    )

    assert result == {"provisioners": [provisioner.id]}
    assert enqueued_provisioners == [provisioner.id]

    second_result = dispatch_due_jobs(
        db_session,
        enqueue_provisioner=lambda provisioner_id: enqueued_provisioners.append(provisioner_id) or "task-provisioner",
        now=now,
    )
    assert second_result == {"provisioners": []}
    assert enqueued_provisioners == [provisioner.id]


def test_dispatch_due_jobs_skips_disabled_provisioners_by_default(db_session: Session) -> None:
    """New provisioners should stay unscheduled until explicitly enabled."""
    now = utcnow()
    platform = Platform(name="Disabled Scheduler")
    provisioner = MachineProvisioner(
        platform=platform,
        name="inventory",
        type="mock_inventory",
        cron="* * * * *",
        last_scheduled_at=now - timedelta(minutes=2),
    )
    db_session.add(provisioner)
    db_session.commit()

    enqueued_provisioners: list[int] = []
    result = dispatch_due_jobs(
        db_session,
        enqueue_provisioner=lambda provisioner_id: enqueued_provisioners.append(provisioner_id) or "task-provisioner",
        now=now,
    )

    assert result == {"provisioners": []}
    assert enqueued_provisioners == []


def test_application_metrics_sync_dispatch_spreads_due_rows(db_session: Session) -> None:
    """Metrics sync dispatch should spread work across ticks."""
    db_session.add_all(
        [
            Application(name="app-a", environment="prod", region="eu"),
            Application(name="app-b", environment="prod", region="eu"),
            Application(name="app-c", environment="prod", region="eu"),
        ]
    )
    db_session.commit()

    enqueued: list[int] = []
    result = dispatch_due_application_metrics_syncs(
        db_session,
        enqueue_application=lambda application_id: enqueued.append(application_id) or "task-application",
        window_days=5,
        tick_seconds=3600,
    )

    assert result == {"applications": [enqueued[0]], "batch_size": 1}
    assert len(enqueued) == 1

    scheduled_count = db_session.query(Application).filter(Application.sync_scheduled_at.is_not(None)).count()
    assert scheduled_count == 1

    second_result = dispatch_due_application_metrics_syncs(
        db_session,
        enqueue_application=lambda application_id: enqueued.append(application_id) or "task-application",
        window_days=5,
        tick_seconds=3600,
    )
    assert second_result == {"applications": [enqueued[1]], "batch_size": 1}
    assert len(enqueued) == 2
