"""Tests covering worker-facing use cases."""

from sqlalchemy import text
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
    """Inventory sync should create machines and capture flavor changes."""
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
    """Provider collection should upsert CPU metrics by day."""
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
        name="cpu",
        type="mock_metric",
        scope="cpu",
        config={"value": 75},
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
    assert sample.date is not None


def test_provider_collection_writes_daily_disk_usage_metric(db_session: Session) -> None:
    """Provider collection should upsert daily disk usage metrics."""
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
        name="disk",
        type="mock_metric",
        scope="disk",
        config={"value": 64},
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
    assert sample.date is not None


def test_placeholder_provisioner_run_is_no_op(db_session: Session) -> None:
    """Placeholder provisioners should succeed without creating machines."""
    platform = Platform(name="Placeholder Inventory")
    provisioner = MachineProvisioner(
        platform=platform,
        name="capsule inventory",
        type="capsule",
        cron="* * * * *",
        config={"token": "capsule-secret"},
    )
    db_session.add(provisioner)
    db_session.commit()

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 0, "updated": 0, "flavor_changes": 0}


def test_placeholder_provider_run_is_no_op(db_session: Session) -> None:
    """Placeholder providers should succeed without writing metrics."""
    platform = Platform(name="Placeholder Metrics")
    provider = MachineProvider(
        platform=platform,
        name="prometheus cpu",
        type="prometheus",
        scope="cpu",
        config={"url": "https://prometheus.example", "query": "avg(up)"},
    )
    db_session.add(provider)
    db_session.commit()

    result = run_provider_collection(db_session, provider.id)
    assert result == {"created": 0, "updated": 0, "skipped": 0}



def test_config_is_encrypted_at_rest(db_session: Session) -> None:
    """Encrypted config columns should not expose secrets in raw SQL."""
    platform = Platform(name="Encrypted Config")
    provisioner = MachineProvisioner(
        platform=platform,
        name="dynatrace inventory",
        type="dynatrace",
        cron="* * * * *",
        config={"url": "https://dynatrace.example", "token": "provisioner-secret"},
    )
    provider = MachineProvider(
        platform=platform,
        name="dynatrace cpu",
        type="dynatrace",
        scope="cpu",
        config={"url": "https://dynatrace.example", "token": "provider-secret"},
    )
    db_session.add_all([provisioner, provider])
    db_session.commit()

    provisioner_raw = db_session.execute(
        text("SELECT config FROM machine_provisioners WHERE id = :id"),
        {"id": provisioner.id},
    ).scalar_one()
    provider_raw = db_session.execute(
        text("SELECT config FROM machine_providers WHERE id = :id"),
        {"id": provider.id},
    ).scalar_one()

    assert isinstance(provisioner_raw, str)
    assert "provisioner-secret" not in provisioner_raw
    assert "dynatrace.example" not in provisioner_raw
    assert isinstance(provider_raw, str)
    assert "provider-secret" not in provider_raw
    assert "dynatrace.example" not in provider_raw

    db_session.expire_all()
    assert db_session.get(MachineProvisioner, provisioner.id).config["token"] == "provisioner-secret"
    assert db_session.get(MachineProvider, provider.id).config["token"] == "provider-secret"


def test_application_sync_marks_success(db_session: Session) -> None:
    """Application sync should record a success payload and timestamps."""
    application = Application(name="catalog", environment="staging", region="eu")
    db_session.add(application)
    db_session.commit()

    result = run_application_sync(db_session, application.id)

    db_session.refresh(application)
    assert result == {"synced": 1}
    assert application.sync_at is not None
    assert application.sync_scheduled_at is None
    assert application.sync_error is None
