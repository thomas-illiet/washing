"""Tests covering worker-facing use cases."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infra.connectors import mock as mock_connectors
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
from internal.usecases.applications import (
    APPLICATION_METRICS_NOT_IMPLEMENTED,
    rebuild_applications_from_machines,
    run_application_metrics_sync,
)
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
                    "application": "checkout",
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
                "application": "checkout",
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
    assert machine.application == "CHECKOUT"
    assert db_session.query(Application).count() == 0
    assert db_session.query(MachineFlavorHistory).count() == 1
    history = db_session.query(MachineFlavorHistory).one()
    assert history.cpu == 4
    assert history.ram_mb == 16 * 1024
    assert history.disk_mb == 120 * 1024


def test_inventory_discovery_rebuild_groups_machine_applications_and_prunes_orphans(db_session: Session) -> None:
    """The application projection should be rebuilt from machine groups only."""
    platform = Platform(name="Projection Platform")
    orphan = Application(name="ORPHAN", environment="prod", region="eu-west-1")
    db_session.add_all(
        [
            platform,
            orphan,
            Machine(
                platform=platform,
                hostname="billing-01",
                application="billing",
                environment="PROD",
                region="EU-WEST-1",
            ),
            Machine(
                platform=platform,
                hostname="billing-02",
                application="BILLING",
                environment="prod",
                region="eu-west-1",
            ),
            Machine(
                platform=platform,
                hostname="catalog-01",
                application=" catalog ",
                environment="Staging",
                region="EU-CENTRAL-1",
            ),
        ]
    )
    db_session.commit()

    result = rebuild_applications_from_machines(db_session)

    applications = (
        db_session.query(Application)
        .order_by(Application.name.asc(), Application.environment.asc(), Application.region.asc())
        .all()
    )
    assert result == {"created": 2, "deleted": 1, "total": 2}
    assert [(item.name, item.environment, item.region) for item in applications] == [
        ("BILLING", "prod", "eu-west-1"),
        ("CATALOG", "staging", "eu-central-1"),
    ]


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


def test_mock_preset_inventory_creates_machines_from_repository_json(db_session: Session) -> None:
    """Mock presets should create inventory rows from the repository JSON payloads."""
    platform = Platform(name="Mock Preset Inventory")
    provisioner = MachineProvisioner(
        platform=platform,
        name="mock preset inventory",
        type="mock",
        cron="* * * * *",
        config={"preset": "small-fleet"},
    )
    db_session.add(provisioner)
    db_session.commit()

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 3, "updated": 0, "flavor_changes": 0}

    machines = db_session.query(Machine).order_by(Machine.hostname.asc()).all()
    assert [machine.hostname for machine in machines] == ["fleet-app-1", "fleet-app-2", "fleet-worker-1"]
    assert [machine.application for machine in machines] == ["CHECKOUT", "CHECKOUT", "PAYMENTS"]


def test_mock_preset_invalid_json_sets_last_error(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid preset files should fail the run and be recorded on the provisioner."""
    preset_dir = tmp_path / "mock"
    preset_dir.mkdir()
    (preset_dir / "single-vm.json").write_text("{invalid json", encoding="utf-8")
    monkeypatch.setattr(mock_connectors, "get_mock_presets_dir", lambda: preset_dir)

    platform = Platform(name="Broken Mock Preset")
    provisioner = MachineProvisioner(
        platform=platform,
        name="broken mock preset",
        type="mock",
        cron="* * * * *",
        config={"preset": "single-vm"},
    )
    db_session.add(provisioner)
    db_session.commit()

    with pytest.raises(json.JSONDecodeError) as exc_info:
        run_provisioner_inventory(db_session, provisioner.id)

    db_session.refresh(provisioner)
    assert provisioner.last_error == str(exc_info.value)


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


def test_application_metrics_sync_marks_not_implemented(db_session: Session) -> None:
    """Application metrics sync should record its controlled placeholder failure."""
    application = Application(name="catalog", environment="staging", region="eu")
    application.sync_scheduled_at = application.created_at if application.created_at else None
    db_session.add(application)
    db_session.commit()

    result = run_application_metrics_sync(db_session, application.id)

    db_session.refresh(application)
    assert result == {"synced": 0, "status": "not_implemented"}
    assert application.sync_at is None
    assert application.sync_scheduled_at is None
    assert application.sync_error == APPLICATION_METRICS_NOT_IMPLEMENTED
