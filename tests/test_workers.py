"""Tests covering worker-facing use cases."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infra.connectors.providers import EmptyMetricCollector
from internal.infra.connectors.providers import mock as mock_metrics
from internal.infra.connectors.provisioners import CapsuleInventoryProvisioner, DynatraceInventoryProvisioner
from internal.infra.connectors.provisioners import mock as mock_provisioners
from internal.infra.connectors.registry import get_machine_provisioner, get_metric_collector
from internal.infra.db.models import (
    Application,
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineRAMMetric,
    MachineProvisioner,
    Platform,
)
from internal.usecases.applications import (
    APPLICATION_METRICS_NOT_IMPLEMENTED,
    rebuild_applications_from_machines,
    run_application_metrics_sync,
)
from internal.usecases.inventory import PROVISIONER_DISABLED_DETAIL, run_provisioner_inventory
from internal.usecases.metrics import run_provider_collection


def test_inventory_tracks_initial_and_changed_flavor_snapshots(db_session: Session) -> None:
    """Inventory sync should persist the initial flavor and later changes."""
    platform = Platform(name="Entity A")
    provisioner = MachineProvisioner(
        platform=platform,
        name="mock inventory",
        type="mock_inventory",
        enabled=True,
        cron="* * * * *",
        config={
            "machines": [
                {
                    "external_id": "vm-1",
                    "hostname": "vm-1",
                    "application": "checkout",
                    "cpu": 2,
                    "ram_mb": 8 * 1024,
                    "disk_mb": 80 * 1024,
                }
            ]
        },
    )
    db_session.add(provisioner)
    db_session.commit()

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 1, "updated": 0, "flavor_changes": 0}

    machine = db_session.query(Machine).filter(Machine.hostname == "VM-1").one()
    history = (
        db_session.query(MachineFlavorHistory)
        .filter(MachineFlavorHistory.machine_id == machine.id)
        .order_by(MachineFlavorHistory.changed_at.asc(), MachineFlavorHistory.id.asc())
        .all()
    )
    assert len(history) == 1
    assert history[0].cpu == 2
    assert history[0].ram_mb == 8 * 1024
    assert history[0].disk_mb == 80 * 1024

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 0, "updated": 1, "flavor_changes": 0}
    assert db_session.query(MachineFlavorHistory).count() == 1

    provisioner.config = {
        "machines": [
            {
                "external_id": "vm-1",
                "hostname": "vm-1",
                "application": "checkout",
                "cpu": 4,
                "ram_mb": 16 * 1024,
                "disk_mb": 120 * 1024,
            }
        ]
    }
    db_session.commit()

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 0, "updated": 1, "flavor_changes": 1}

    machine = db_session.query(Machine).filter(Machine.hostname == "VM-1").one()
    assert machine.cpu == 4
    assert machine.application == "CHECKOUT"
    assert db_session.query(Application).count() == 0
    history = (
        db_session.query(MachineFlavorHistory)
        .filter(MachineFlavorHistory.machine_id == machine.id)
        .order_by(MachineFlavorHistory.changed_at.asc(), MachineFlavorHistory.id.asc())
        .all()
    )
    assert len(history) == 2
    assert history[1].cpu == 4
    assert history[1].ram_mb == 16 * 1024
    assert history[1].disk_mb == 120 * 1024


def test_disabled_provisioner_run_is_rejected(db_session: Session) -> None:
    """Disabled provisioners should fail fast instead of syncing inventory."""
    platform = Platform(name="Disabled Inventory")
    provisioner = MachineProvisioner(
        platform=platform,
        name="disabled inventory",
        type="mock_inventory",
        cron="* * * * *",
        config={"machines": [{"external_id": "vm-1", "hostname": "vm-1"}]},
    )
    db_session.add(provisioner)
    db_session.commit()

    with pytest.raises(ValueError, match=PROVISIONER_DISABLED_DETAIL):
        run_provisioner_inventory(db_session, provisioner.id)

    db_session.refresh(provisioner)
    assert provisioner.last_error == PROVISIONER_DISABLED_DETAIL
    assert provisioner.last_run_at is not None
    assert db_session.query(Machine).count() == 0


def test_inventory_discovery_rebuild_groups_machine_applications_and_prunes_orphans(db_session: Session) -> None:
    """The application projection should be rebuilt from machine groups only."""
    platform = Platform(name="Projection Platform")
    orphan = Application(name="ORPHAN", environment="PROD", region="EU-WEST-1")
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
        ("BILLING", "PROD", "EU-WEST-1"),
        ("CATALOG", "STAGING", "EU-CENTRAL-1"),
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
        ram_mb=8 * 1024,
        disk_mb=80 * 1024,
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
        ram_mb=8 * 1024,
        disk_mb=80 * 1024,
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


@pytest.mark.parametrize(
    ("scope", "metric_model"),
    [
        ("cpu", MachineCPUMetric),
        ("ram", MachineRAMMetric),
        ("disk", MachineDiskMetric),
    ],
)
def test_provider_collection_generates_random_metric_in_scope(
    db_session: Session,
    scope: str,
    metric_model: type[MachineCPUMetric | MachineRAMMetric | MachineDiskMetric],
) -> None:
    """Mock providers should generate one bounded random sample for their scope."""
    platform = Platform(name=f"Random {scope.upper()} Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id=f"{scope}-vm-1",
        hostname=f"{scope}-vm-1",
    )
    provider = MachineProvider(
        platform=platform,
        name=f"{scope} random",
        type="mock_metric",
        scope=scope,
        config={},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    result = run_provider_collection(db_session, provider.id)

    assert result == {"created": 1, "updated": 0, "skipped": 0}
    sample = db_session.query(metric_model).one()
    assert sample.provider_id == provider.id
    assert sample.machine_id == machine.id
    assert 0 <= sample.value <= 100
    assert sample.date is not None

    other_counts = {
        MachineCPUMetric: db_session.query(MachineCPUMetric).count(),
        MachineRAMMetric: db_session.query(MachineRAMMetric).count(),
        MachineDiskMetric: db_session.query(MachineDiskMetric).count(),
    }
    for model, count in other_counts.items():
        expected_count = 1 if model is metric_model else 0
        assert count == expected_count


def test_provider_collection_draws_one_random_value_per_machine(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock providers should draw a fallback random value for each machine independently."""
    calls: list[tuple[int, int]] = []

    def fake_randint(lower_bound: int, upper_bound: int) -> int:
        calls.append((lower_bound, upper_bound))
        return 50

    monkeypatch.setattr(mock_metrics.random, "randint", fake_randint)

    platform = Platform(name="Per Machine Random Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machines = [
        Machine(platform=platform, source_provisioner=provisioner, external_id="vm-1", hostname="vm-1"),
        Machine(platform=platform, source_provisioner=provisioner, external_id="vm-2", hostname="vm-2"),
    ]
    provider = MachineProvider(
        platform=platform,
        name="cpu random",
        type="mock_metric",
        scope="cpu",
        config={},
        provisioners=[provisioner],
    )
    db_session.add_all([*machines, provider])
    db_session.commit()

    result = run_provider_collection(db_session, provider.id)

    assert result == {"created": 2, "updated": 0, "skipped": 0}
    assert calls == [(0, 100), (0, 100)]
    assert [sample.value for sample in db_session.query(MachineCPUMetric).order_by(MachineCPUMetric.id.asc()).all()] == [50, 50]


def test_provider_collection_values_by_hostname_override_random(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hostname-specific values should win over the random fallback."""
    monkeypatch.setattr(mock_metrics.random, "randint", lambda _lower_bound, _upper_bound: 12)

    platform = Platform(name="Hostname Override Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machines = [
        Machine(platform=platform, source_provisioner=provisioner, external_id="vm-1", hostname="vm-1"),
        Machine(platform=platform, source_provisioner=provisioner, external_id="vm-2", hostname="vm-2"),
    ]
    provider = MachineProvider(
        platform=platform,
        name="cpu hostname override",
        type="mock_metric",
        scope="cpu",
        config={"values_by_hostname": {"vm-1": 88}},
        provisioners=[provisioner],
    )
    db_session.add_all([*machines, provider])
    db_session.commit()

    result = run_provider_collection(db_session, provider.id)

    assert result == {"created": 2, "updated": 0, "skipped": 0}
    values_by_machine = {
        sample.machine_id: sample.value
        for sample in db_session.query(MachineCPUMetric).order_by(MachineCPUMetric.machine_id.asc()).all()
    }
    assert values_by_machine[machines[0].id] == 88
    assert values_by_machine[machines[1].id] == 12


def test_provider_collection_value_overrides_random(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fixed mock value should disable the random fallback."""

    def unexpected_randint(_lower_bound: int, _upper_bound: int) -> int:
        raise AssertionError("random fallback should not be used when value is configured")

    monkeypatch.setattr(mock_metrics.random, "randint", unexpected_randint)

    platform = Platform(name="Fixed Value Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(platform=platform, source_provisioner=provisioner, external_id="vm-1", hostname="vm-1")
    provider = MachineProvider(
        platform=platform,
        name="cpu fixed value",
        type="mock_metric",
        scope="cpu",
        config={"value": 73},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    result = run_provider_collection(db_session, provider.id)

    assert result == {"created": 1, "updated": 0, "skipped": 0}
    assert db_session.query(MachineCPUMetric).one().value == 73


def test_mock_preset_inventory_creates_machines_from_repository_json(db_session: Session) -> None:
    """Mock presets should create inventory rows from the repository JSON payloads."""
    platform = Platform(name="Mock Preset Inventory")
    provisioner = MachineProvisioner(
        platform=platform,
        name="mock preset inventory",
        type="mock",
        enabled=True,
        cron="* * * * *",
        config={"preset": "small-fleet"},
    )
    db_session.add(provisioner)
    db_session.commit()

    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 3, "updated": 0, "flavor_changes": 0}

    machines = db_session.query(Machine).order_by(Machine.hostname.asc()).all()
    assert [machine.hostname for machine in machines] == ["FLEET-APP-1", "FLEET-APP-2", "FLEET-WORKER-1"]
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
    monkeypatch.setattr(mock_provisioners, "get_mock_presets_dir", lambda: preset_dir)

    platform = Platform(name="Broken Mock Preset")
    provisioner = MachineProvisioner(
        platform=platform,
        name="broken mock preset",
        type="mock",
        enabled=True,
        cron="* * * * *",
        config={"preset": "single-vm"},
    )
    db_session.add(provisioner)
    db_session.commit()

    with pytest.raises(json.JSONDecodeError) as exc_info:
        run_provisioner_inventory(db_session, provisioner.id)

    db_session.refresh(provisioner)
    assert provisioner.last_error == str(exc_info.value)


@pytest.mark.parametrize(
    ("connector_type", "config", "expected_connector"),
    [
        ("capsule", {"token": "capsule-secret"}, CapsuleInventoryProvisioner),
        (
            "dynatrace",
            {"url": "https://dynatrace.example", "token": "dynatrace-secret"},
            DynatraceInventoryProvisioner,
        ),
    ],
)
def test_placeholder_provisioner_run_is_no_op(
    db_session: Session,
    connector_type: str,
    config: dict[str, str],
    expected_connector: type[CapsuleInventoryProvisioner | DynatraceInventoryProvisioner],
) -> None:
    """Placeholder provisioners should succeed without creating machines."""
    platform = Platform(name=f"Placeholder {connector_type.title()} Inventory")
    provisioner = MachineProvisioner(
        platform=platform,
        name=f"{connector_type} inventory",
        type=connector_type,
        enabled=True,
        cron="* * * * *",
        config=config,
    )
    db_session.add(provisioner)
    db_session.commit()

    assert isinstance(get_machine_provisioner(connector_type), expected_connector)
    result = run_provisioner_inventory(db_session, provisioner.id)
    assert result == {"created": 0, "updated": 0, "flavor_changes": 0}


@pytest.mark.parametrize(
    ("connector_type", "scope", "config"),
    [
        ("prometheus", "cpu", {"url": "https://prometheus.example", "query": "avg(up)"}),
        ("dynatrace", "disk", {"url": "https://dynatrace.example", "token": "provider-secret"}),
    ],
)
def test_placeholder_provider_run_is_no_op(
    db_session: Session,
    connector_type: str,
    scope: str,
    config: dict[str, str],
) -> None:
    """Placeholder providers should succeed without writing metrics."""
    platform = Platform(name="Placeholder Metrics")
    provider = MachineProvider(
        platform=platform,
        name=f"{connector_type} {scope}",
        type=connector_type,
        scope=scope,
        config=config,
    )
    db_session.add(provider)
    db_session.commit()

    assert isinstance(get_metric_collector(connector_type), EmptyMetricCollector)
    result = run_provider_collection(db_session, provider.id)
    assert result == {"created": 0, "updated": 0, "skipped": 0}
    assert db_session.query(MachineCPUMetric).count() == 0
    assert db_session.query(MachineRAMMetric).count() == 0
    assert db_session.query(MachineDiskMetric).count() == 0


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
