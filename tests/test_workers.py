from sqlalchemy.orm import Session

from internal.infra.db.models import (
    Application,
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineProvisioner,
    Platform,
)
from internal.usecases.applications import run_application_sync
from internal.usecases.inventory import run_provisioner_inventory
from internal.usecases.metrics import run_provider_collection


def test_inventory_creates_machine_and_records_flavor_change(db_session: Session) -> None:
    platform = Platform(name="Entity A")
    provisioner = MachineProvisioner(
        platform=platform,
        name="mock inventory",
        type="mock_inventory",
        cron="* * * * *",
        config={
            "machines": [
                {
                    "external_id": "vm-1",
                    "hostname": "vm-1",
                    "application_name": "checkout",
                    "cpu": 2,
                    "ram_gb": 8,
                    "disk_gb": 80,
                }
            ]
        },
    )
    db_session.add(provisioner)
    db_session.commit()

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 1, "updated": 0, "flavor_changes": 0}

    provisioner.config = {
        "machines": [
            {
                "external_id": "vm-1",
                "hostname": "vm-1",
                "application_name": "checkout",
                "cpu": 4,
                "ram_gb": 16,
                "disk_gb": 120,
            }
        ]
    }
    db_session.commit()

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 0, "updated": 1, "flavor_changes": 1}

    machine = db_session.query(Machine).filter(Machine.hostname == "vm-1").one()
    assert machine.cpu == 4
    assert machine.application_id is not None
    assert db_session.query(Application).filter(Application.name == "checkout").count() == 1
    assert db_session.query(MachineFlavorHistory).count() == 1


def test_provider_collection_writes_cpu_metric(db_session: Session) -> None:
    platform = Platform(name="Entity B")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-1",
        hostname="vm-1",
        cpu=2,
        ram_gb=8,
        disk_gb=80,
    )
    provider = MachineProvider(
        platform=platform,
        metric_type_id=1,
        name="cpu",
        type="mock_metric",
        cron="* * * * *",
        config={"value": 75, "percentile": 99},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    result = run_provider_collection(db_session, provider.id)
    assert result == {"created": 1, "updated": 0, "skipped": 0}

    second_result = run_provider_collection(db_session, provider.id)
    assert second_result == {"created": 0, "updated": 1, "skipped": 0}

    sample = db_session.query(MachineCPUMetric).one()
    assert sample.provider_id == provider.id
    assert sample.machine_id == machine.id
    assert sample.value == 75
    assert sample.percentile == 99
    assert sample.metric_date == sample.collected_at.date()


def test_provider_collection_writes_daily_disk_usage_metric(db_session: Session) -> None:
    platform = Platform(name="Entity C")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-2",
        hostname="vm-2",
        cpu=2,
        ram_gb=8,
        disk_gb=80,
    )
    provider = MachineProvider(
        platform=platform,
        metric_type_id=3,
        name="disk",
        type="mock_metric",
        cron="* * * * *",
        config={"value": 64, "usage_type": "used"},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    result = run_provider_collection(db_session, provider.id)
    assert result == {"created": 1, "updated": 0, "skipped": 0}

    sample = db_session.query(MachineDiskMetric).one()
    assert sample.provider_id == provider.id
    assert sample.machine_id == machine.id
    assert sample.value == 64
    assert sample.usage_type == "used"


def test_application_sync_marks_success(db_session: Session) -> None:
    application = Application(name="catalog", environment="staging", region="eu")
    db_session.add(application)
    db_session.commit()

    result = run_application_sync(db_session, application.id)

    db_session.refresh(application)
    assert result == {"synced": 1}
    assert application.sync_at is not None
    assert application.sync_scheduled_at is None
    assert application.sync_error is None
