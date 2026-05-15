"""Tests for maintenance cleanup use cases."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from internal.infra.db.models import (
    Application,
    Machine,
    MachineCPUMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineProvisioner,
    MachineOptimization,
    Platform,
)
from internal.usecases.maintenance import purge_stale_applications, purge_stale_machines


def test_purge_stale_machines_deletes_only_old_machine_rows(db_session: Session) -> None:
    """Machine retention should clean stale machine rows without touching application projection rows."""
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)

    platform = Platform(name="main")
    provisioner = MachineProvisioner(
        platform=platform,
        name="inventory",
        type="mock_inventory",
        config={"preset": "single-vm"},
        enabled=True,
    )
    provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        config={},
        enabled=True,
    )
    old_machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        application="legacy-app",
        external_id="legacy-001",
        hostname="legacy-001",
        environment="prod",
        region="eu-west-1",
        updated_at=now - timedelta(days=20),
    )
    fresh_machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        application="fresh-app",
        external_id="fresh-001",
        hostname="fresh-001",
        environment="prod",
        region="eu-west-1",
        updated_at=now - timedelta(days=2),
    )
    db_session.add_all(
        [
            platform,
            provisioner,
            provider,
            old_machine,
            fresh_machine,
            Application(name="legacy-app", environment="prod", region="eu-west-1"),
            Application(name="fresh-app", environment="prod", region="eu-west-1"),
        ]
    )
    db_session.flush()

    old_machine_id = old_machine.id
    fresh_machine_id = fresh_machine.id

    db_session.add_all(
        [
            MachineFlavorHistory(
                machine_id=old_machine_id,
                source_provisioner_id=provisioner.id,
                cpu=2,
                ram_mb=4096,
                disk_mb=51200,
            ),
            MachineCPUMetric(
                provider_id=provider.id,
                machine_id=old_machine_id,
                date=date(2026, 5, 1),
                value=42,
            ),
            MachineOptimization(
                machine_id=old_machine_id,
                status="partial",
                action="insufficient_data",
                window_size=30,
                min_cpu=1,
                max_cpu=64,
                min_ram_mb=2048,
                max_ram_mb=262144,
                computed_at=now,
                current_cpu=2,
                current_ram_mb=4096,
                current_disk_mb=51200,
                details={},
            ),
        ]
    )
    db_session.commit()

    result = purge_stale_machines(db_session, retention_days=15, now=now)

    assert result == {"deleted": 1, "status": "completed"}
    assert db_session.query(Machine).filter(Machine.id == old_machine_id).one_or_none() is None
    assert db_session.query(Machine).filter(Machine.id == fresh_machine_id).one_or_none() is not None
    assert db_session.query(MachineFlavorHistory).filter(MachineFlavorHistory.machine_id == old_machine_id).count() == 0
    assert db_session.query(MachineCPUMetric).filter(MachineCPUMetric.machine_id == old_machine_id).count() == 0
    assert db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == old_machine_id).count() == 0
    assert db_session.query(Application).count() == 2


def test_purge_stale_applications_deletes_only_old_application_rows(db_session: Session) -> None:
    """Application retention should clean stale applications without touching machine inventory rows."""
    now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)

    platform = Platform(name="main")
    provisioner = MachineProvisioner(
        platform=platform,
        name="inventory",
        type="mock_inventory",
        config={"preset": "single-vm"},
        enabled=True,
    )
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        application="fresh-machine-app",
        external_id="machine-001",
        hostname="machine-001",
        environment="prod",
        region="eu-west-1",
        updated_at=now - timedelta(days=3),
    )
    old_application = Application(
        name="legacy-app",
        environment="prod",
        region="eu-west-1",
        updated_at=now - timedelta(days=20),
    )
    fresh_application = Application(
        name="fresh-app",
        environment="prod",
        region="eu-west-1",
        updated_at=now - timedelta(days=2),
    )
    db_session.add_all([platform, provisioner, machine, old_application, fresh_application])
    db_session.commit()

    machine_id = machine.id
    fresh_application_id = fresh_application.id
    old_application_id = old_application.id

    result = purge_stale_applications(db_session, retention_days=15, now=now)

    assert result == {"deleted": 1, "status": "completed"}
    assert db_session.query(Application).filter(Application.id == old_application_id).one_or_none() is None
    assert db_session.query(Application).filter(Application.id == fresh_application_id).one_or_none() is not None
    assert db_session.query(Machine).filter(Machine.id == machine_id).one_or_none() is not None
