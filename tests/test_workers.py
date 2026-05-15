"""Tests covering worker-facing use cases."""

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infra.connectors.base import MetricRecord
from internal.infra.connectors.providers import EmptyMetricCollector
from internal.infra.connectors.providers import mock as mock_metrics
from internal.infra.connectors.provisioners import CapsuleInventoryProvisioner, DynatraceInventoryProvisioner
from internal.infra.connectors.provisioners import mock as mock_provisioners
from internal.infra.connectors.registry import get_machine_provisioner, get_metric_collector
from internal.infra.security.sanitization import DISABLED_ERROR, INVALID_CONFIGURATION_ERROR
from internal.infra.db.models import (
    Application,
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineRAMMetric,
    MachineOptimization,
    MachineProvisioner,
    Platform,
)
from internal.infra.config.settings import get_settings
from internal.usecases.applications import (
    rebuild_applications_from_machines,
    run_application_metrics_sync,
)
from internal.usecases.inventory import PROVISIONER_DISABLED_DETAIL, run_provisioner_inventory
from internal.usecases.metrics import (
    dispatch_enabled_provider_syncs,
    dispatch_provider_machine_syncs,
    run_provider_machine_collection,
)
from internal.usecases.optimizations import refresh_machine_optimization


def _configure_optimization_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    window_size: int = 1,
    min_cpu: int = 1,
    max_cpu: int = 64,
    min_ram_mb: int = 2048,
    max_ram_mb: int = 262144,
) -> None:
    """Override optimization settings for deterministic worker tests."""
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_WINDOW_SIZE", str(window_size))
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MIN_CPU", str(min_cpu))
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MAX_CPU", str(max_cpu))
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MIN_RAM_MB", str(min_ram_mb))
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MAX_RAM_MB", str(max_ram_mb))
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_cached_settings_after_test():
    """Keep cached settings isolated between worker tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
    assert provisioner.last_error == DISABLED_ERROR
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


def test_dispatch_enabled_provider_syncs_enqueues_enabled_providers_only(db_session: Session) -> None:
    """Global provider dispatch should only enqueue enabled providers in id order."""
    platform = Platform(name="Enabled Provider Dispatch")
    providers = [
        MachineProvider(
            platform=platform,
            name="disabled cpu",
            type="prometheus",
            scope="cpu",
            config={"url": "https://prometheus.example", "query": "avg(up)"},
        ),
        MachineProvider(
            platform=platform,
            name="enabled ram",
            type="dynatrace",
            scope="ram",
            enabled=True,
            config={"url": "https://dynatrace.example", "token": "provider-secret"},
        ),
        MachineProvider(
            platform=platform,
            name="enabled disk",
            type="mock_metric",
            scope="disk",
            enabled=True,
            config={"value": 61},
        ),
    ]
    db_session.add_all([platform, *providers])
    db_session.commit()

    enqueued: list[int] = []
    result = dispatch_enabled_provider_syncs(
        db_session,
        enqueue_provider=lambda provider_id: enqueued.append(provider_id) or f"provider-{provider_id}",
    )

    expected_ids = [providers[1].id, providers[2].id]
    assert result == {"providers": expected_ids}
    assert enqueued == expected_ids


def test_dispatch_provider_machine_syncs_enqueues_visible_machines(db_session: Session) -> None:
    """Provider dispatch should enqueue one child task per visible machine."""
    platform = Platform(name="Provider Machine Dispatch")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    other_provisioner = MachineProvisioner(platform=platform, name="other", type="mock_inventory", cron="* * * * *")
    machines = [
        Machine(platform=platform, source_provisioner=provisioner, external_id="vm-1", hostname="vm-1"),
        Machine(platform=platform, source_provisioner=provisioner, external_id="vm-2", hostname="vm-2"),
        Machine(platform=platform, source_provisioner=other_provisioner, external_id="vm-3", hostname="vm-3"),
    ]
    provider = MachineProvider(
        platform=platform,
        name="cpu mock",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 44},
        provisioners=[provisioner],
    )
    db_session.add_all([*machines, provider])
    db_session.commit()

    enqueued: list[tuple[int, int]] = []
    result = dispatch_provider_machine_syncs(
        db_session,
        provider.id,
        enqueue_machine_sync=lambda provider_id, machine_id: enqueued.append((provider_id, machine_id))
        or f"{provider_id}-{machine_id}",
    )

    db_session.refresh(provider)
    assert result == {"provider_id": provider.id, "machines": [machines[0].id, machines[1].id]}
    assert enqueued == [(provider.id, machines[0].id), (provider.id, machines[1].id)]
    assert provider.last_run_at is not None
    assert provider.last_error is None


def test_provider_machine_collection_writes_cpu_metric(db_session: Session) -> None:
    """One provider/machine task should upsert a CPU metric by day."""
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

    result = run_provider_machine_collection(db_session, provider.id, machine.id)
    assert result == {"provider_id": provider.id, "machine_id": machine.id, "created": 1, "updated": 0, "skipped": 0}

    second_result = run_provider_machine_collection(db_session, provider.id, machine.id)
    assert second_result == {
        "provider_id": provider.id,
        "machine_id": machine.id,
        "created": 0,
        "updated": 1,
        "skipped": 0,
    }

    sample = db_session.query(MachineCPUMetric).one()
    assert sample.provider_id == provider.id
    assert sample.machine_id == machine.id
    assert sample.value == 75
    assert sample.date is not None


def test_provider_machine_collection_writes_multiple_daily_samples(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One provider/machine task should upsert every returned daily sample."""
    platform = Platform(name="Historical Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-history",
        hostname="vm-history",
    )
    provider = MachineProvider(
        platform=platform,
        name="cpu history",
        type="mock_metric",
        scope="cpu",
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    first_records = [
        MetricRecord(value=42, date=date(2026, 5, 13), machine_id=machine.id),
        MetricRecord(value=57, date=date(2026, 5, 14), machine_id=machine.id),
    ]
    second_records = [
        MetricRecord(value=45, date=date(2026, 5, 13), machine_id=machine.id),
        MetricRecord(value=60, date=date(2026, 5, 14), machine_id=machine.id),
    ]
    collections = iter([first_records, second_records])

    class HistoricalMetricCollector:
        def collect(self, _provider: MachineProvider, _machines: list[Machine]) -> list[MetricRecord]:
            return next(collections)

    monkeypatch.setattr(
        "internal.usecases.metrics.get_metric_collector",
        lambda _connector_type: HistoricalMetricCollector(),
    )

    result = run_provider_machine_collection(db_session, provider.id, machine.id)
    assert result == {"provider_id": provider.id, "machine_id": machine.id, "created": 2, "updated": 0, "skipped": 0}

    second_result = run_provider_machine_collection(db_session, provider.id, machine.id)
    assert second_result == {
        "provider_id": provider.id,
        "machine_id": machine.id,
        "created": 0,
        "updated": 2,
        "skipped": 0,
    }

    samples = db_session.query(MachineCPUMetric).order_by(MachineCPUMetric.date.asc()).all()
    assert [(sample.date, sample.value) for sample in samples] == [
        (date(2026, 5, 13), 45),
        (date(2026, 5, 14), 60),
    ]


def test_provider_machine_collection_writes_daily_disk_usage_metric(db_session: Session) -> None:
    """One provider/machine task should upsert a disk metric."""
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

    result = run_provider_machine_collection(db_session, provider.id, machine.id)
    assert result == {"provider_id": provider.id, "machine_id": machine.id, "created": 1, "updated": 0, "skipped": 0}

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
def test_provider_machine_collection_generates_random_metric_in_scope(
    db_session: Session,
    scope: str,
    metric_model: type[MachineCPUMetric | MachineRAMMetric | MachineDiskMetric],
) -> None:
    """Mock providers should generate one bounded random sample per machine task."""
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

    result = run_provider_machine_collection(db_session, provider.id, machine.id)

    assert result == {"provider_id": provider.id, "machine_id": machine.id, "created": 1, "updated": 0, "skipped": 0}
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


def test_provider_machine_collection_draws_one_random_value_per_machine(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running one child task per machine should distribute random fallback draws."""
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

    first_result = run_provider_machine_collection(db_session, provider.id, machines[0].id)
    second_result = run_provider_machine_collection(db_session, provider.id, machines[1].id)

    assert first_result == {
        "provider_id": provider.id,
        "machine_id": machines[0].id,
        "created": 1,
        "updated": 0,
        "skipped": 0,
    }
    assert second_result == {
        "provider_id": provider.id,
        "machine_id": machines[1].id,
        "created": 1,
        "updated": 0,
        "skipped": 0,
    }
    assert calls == [(0, 100), (0, 100)]
    assert [sample.value for sample in db_session.query(MachineCPUMetric).order_by(MachineCPUMetric.id.asc()).all()] == [50, 50]


def test_provider_machine_collection_values_by_hostname_override_random(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hostname-specific overrides should still apply with one task per machine."""
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

    first_result = run_provider_machine_collection(db_session, provider.id, machines[0].id)
    second_result = run_provider_machine_collection(db_session, provider.id, machines[1].id)

    assert first_result["created"] == 1
    assert second_result["created"] == 1
    values_by_machine = {
        sample.machine_id: sample.value
        for sample in db_session.query(MachineCPUMetric).order_by(MachineCPUMetric.machine_id.asc()).all()
    }
    assert values_by_machine[machines[0].id] == 88
    assert values_by_machine[machines[1].id] == 12


def test_provider_machine_collection_value_overrides_random(
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

    result = run_provider_machine_collection(db_session, provider.id, machine.id)

    assert result == {"provider_id": provider.id, "machine_id": machine.id, "created": 1, "updated": 0, "skipped": 0}
    assert db_session.query(MachineCPUMetric).one().value == 73


def test_provider_machine_collection_skips_missing_or_out_of_scope_machine(db_session: Session) -> None:
    """Missing or out-of-scope machines should end as skipped, not failures."""
    platform = Platform(name="Skipped Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    other_provisioner = MachineProvisioner(platform=platform, name="other", type="mock_inventory", cron="* * * * *")
    scoped_machine = Machine(platform=platform, source_provisioner=provisioner, external_id="vm-1", hostname="vm-1")
    out_of_scope_machine = Machine(
        platform=platform,
        source_provisioner=other_provisioner,
        external_id="vm-2",
        hostname="vm-2",
    )
    provider = MachineProvider(
        platform=platform,
        name="cpu scoped",
        type="mock_metric",
        scope="cpu",
        config={"value": 41},
        provisioners=[provisioner],
    )
    db_session.add_all([scoped_machine, out_of_scope_machine, provider])
    db_session.commit()

    missing_result = run_provider_machine_collection(db_session, provider.id, 9999)
    out_of_scope_result = run_provider_machine_collection(db_session, provider.id, out_of_scope_machine.id)

    assert missing_result == {
        "provider_id": provider.id,
        "machine_id": 9999,
        "created": 0,
        "updated": 0,
        "skipped": 1,
        "status": "machine_not_found",
    }
    assert out_of_scope_result == {
        "provider_id": provider.id,
        "machine_id": out_of_scope_machine.id,
        "created": 0,
        "updated": 0,
        "skipped": 1,
        "status": "machine_out_of_scope",
    }
    assert db_session.query(MachineCPUMetric).count() == 0


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
    assert exc_info.value is not None
    assert provisioner.last_error == INVALID_CONFIGURATION_ERROR


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
    machine = Machine(platform=platform, external_id="vm-1", hostname="vm-1")
    provider = MachineProvider(
        platform=platform,
        name=f"{connector_type} {scope}",
        type=connector_type,
        scope=scope,
        config=config,
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    assert isinstance(get_metric_collector(connector_type), EmptyMetricCollector)
    result = run_provider_machine_collection(db_session, provider.id, machine.id)
    assert result == {
        "provider_id": provider.id,
        "machine_id": machine.id,
        "created": 0,
        "updated": 0,
        "skipped": 1,
    }
    db_session.refresh(provider)
    assert provider.last_success_at is not None
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


def test_application_metrics_sync_dispatches_machine_provider_pairs(db_session: Session) -> None:
    """Application metrics sync should batch by application and dispatch provider/machine child tasks."""
    platform = Platform(name="Application Metrics Dispatch")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    other_platform = Platform(name="Other Application Metrics Dispatch")
    db_session.add_all(
        [
            platform,
            other_platform,
            Machine(
                platform=platform,
                source_provisioner=provisioner,
                application="catalog",
                environment="staging",
                region="eu",
                external_id="vm-1",
                hostname="catalog-1",
            ),
            Machine(
                platform=platform,
                source_provisioner=provisioner,
                application="catalog",
                environment="staging",
                region="eu",
                external_id="vm-2",
                hostname="catalog-2",
            ),
            Machine(
                platform=platform,
                source_provisioner=provisioner,
                application="payments",
                environment="staging",
                region="eu",
                external_id="vm-3",
                hostname="payments-1",
            ),
        ]
    )
    db_session.commit()
    application = Application(name="catalog", environment="staging", region="eu")
    application.sync_scheduled_at = application.created_at if application.created_at else None
    provider_cpu = MachineProvider(
        platform=platform,
        name="catalog cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 70},
        provisioners=[provisioner],
    )
    provider_ram = MachineProvider(
        platform=platform,
        name="catalog ram",
        type="mock_metric",
        scope="ram",
        enabled=True,
        config={"value": 55},
    )
    provider_disabled = MachineProvider(
        platform=platform,
        name="catalog disk disabled",
        type="mock_metric",
        scope="disk",
        config={"value": 40},
    )
    provider_other_platform = MachineProvider(
        platform=other_platform,
        name="other platform cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 90},
    )
    db_session.add_all([application, provider_cpu, provider_ram, provider_disabled, provider_other_platform])
    db_session.commit()

    enqueued: list[tuple[int, int]] = []
    result = run_application_metrics_sync(
        db_session,
        application.id,
        enqueue_machine_sync=lambda provider_id, machine_id: enqueued.append((provider_id, machine_id))
        or f"{provider_id}-{machine_id}",
    )

    expected_pairs = [
        (provider_cpu.id, machine.id)
        for machine in db_session.query(Machine)
        .filter(Machine.application == "CATALOG")
        .order_by(Machine.id.asc())
        .all()
    ] + [
        (provider_ram.id, machine.id)
        for machine in db_session.query(Machine)
        .filter(Machine.application == "CATALOG")
        .order_by(Machine.id.asc())
        .all()
    ]
    db_session.refresh(application)
    assert result == {"application_id": application.id, "machines": 2, "synced": 4, "status": "dispatched"}
    assert enqueued == [(provider_id, machine_id) for provider_id, machine_id in sorted(expected_pairs, key=lambda item: (item[1], item[0]))]
    assert application.sync_at is not None
    assert application.sync_scheduled_at is None
    assert application.sync_error is None


def test_provider_machine_collection_creates_optimization_and_updates_on_noop(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automatic optimization refreshes should keep a single optimization row on no-op runs."""
    _configure_optimization_settings(monkeypatch, window_size=1)

    platform = Platform(name="Optimization Auto Refresh")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-1",
        hostname="vm-1",
        cpu=2,
        ram_mb=4096,
        disk_mb=80 * 1024,
    )
    provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 90},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    first_result = run_provider_machine_collection(db_session, provider.id, machine.id)
    second_result = run_provider_machine_collection(db_session, provider.id, machine.id)

    assert first_result == {"provider_id": provider.id, "machine_id": machine.id, "created": 1, "updated": 0, "skipped": 0}
    assert second_result == {"provider_id": provider.id, "machine_id": machine.id, "created": 0, "updated": 1, "skipped": 0}

    optimizations = (
        db_session.query(MachineOptimization)
        .filter(MachineOptimization.machine_id == machine.id)
        .order_by(MachineOptimization.id.asc())
        .all()
    )
    assert len(optimizations) == 1
    assert optimizations[0].status == "partial"
    assert optimizations[0].details["cpu"]["action"] == "scale_up"
    assert optimizations[0].details["ram"]["status"] == "missing_provider"


def test_refresh_machine_optimization_updates_existing_row_when_snapshot_changes(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed optimization snapshot should update the existing projection row."""
    _configure_optimization_settings(monkeypatch, window_size=1)

    platform = Platform(name="Optimization Revisions")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-2",
        hostname="vm-2",
        cpu=4,
        ram_mb=8192,
        disk_mb=80 * 1024,
    )
    provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 90},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    db_session.add(MachineCPUMetric(provider_id=provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=90))
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    sample = db_session.query(MachineCPUMetric).one()
    sample.value = 20
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimizations = (
        db_session.query(MachineOptimization)
        .filter(MachineOptimization.machine_id == machine.id)
        .order_by(MachineOptimization.id.asc())
        .all()
    )
    assert len(optimizations) == 1
    assert optimizations[0].details["cpu"]["action"] == "scale_down"


def test_refresh_machine_optimization_averages_available_metric_window(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optimization refreshes should use the average utilization across loaded samples."""
    _configure_optimization_settings(monkeypatch, window_size=3)

    platform = Platform(name="Optimization Average Window")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-average",
        hostname="vm-average",
        cpu=4,
        ram_mb=8192,
        disk_mb=80 * 1024,
    )
    provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 90},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    db_session.add_all(
        [
            MachineCPUMetric(provider_id=provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=80),
            MachineCPUMetric(provider_id=provider.id, machine_id=machine.id, date=date(2026, 5, 2), value=90),
            MachineCPUMetric(provider_id=provider.id, machine_id=machine.id, date=date(2026, 5, 3), value=100),
        ]
    )
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimization = db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == machine.id).one()
    assert optimization.details["cpu"]["utilization_percent"] == 90
    assert optimization.details["cpu"]["reason_code"] == "pressure_high"
    assert optimization.target_cpu == 6


def test_refresh_machine_optimization_uses_partial_windows_and_reports_ambiguous_providers(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optimization refreshes should calculate partial windows and surface provider ambiguity."""
    _configure_optimization_settings(monkeypatch, window_size=2)

    platform = Platform(name="Optimization Edge Cases")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-3",
        hostname="vm-3",
        cpu=2,
        ram_mb=4096,
        disk_mb=80 * 1024,
    )
    provider_one = MachineProvider(
        platform=platform,
        name="cpu one",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 85},
        provisioners=[provisioner],
    )
    provider_two = MachineProvider(
        platform=platform,
        name="cpu two",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 83},
    )
    ram_provider = MachineProvider(
        platform=platform,
        name="ram one",
        type="mock_metric",
        scope="ram",
        enabled=True,
        config={"value": 35},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider_one, provider_two, ram_provider])
    db_session.commit()

    db_session.add(MachineRAMMetric(provider_id=ram_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=35))
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimization = db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == machine.id).one()
    assert optimization.status == "error"
    assert optimization.action == "scale_down"
    assert optimization.details["cpu"]["status"] == "ambiguous_provider"
    assert optimization.details["ram"]["status"] == "ok"
    assert optimization.details["ram"]["action"] == "scale_down"
    assert optimization.details["ram"]["reason_code"] == "limited_history"
    assert optimization.details["ram"]["utilization_percent"] == 35
    assert optimization.details["disk"]["status"] == "missing_provider"


def test_refresh_machine_optimization_reports_zero_samples_as_insufficient_data(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A visible provider without samples should keep its scope non-calculable."""
    _configure_optimization_settings(monkeypatch, window_size=2)

    platform = Platform(name="Optimization Zero Samples")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-3-empty",
        hostname="vm-3-empty",
        cpu=2,
        ram_mb=4096,
        disk_mb=80 * 1024,
    )
    provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 85},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, provider])
    db_session.commit()

    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimization = db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == machine.id).one()
    assert optimization.details["cpu"]["status"] == "insufficient_data"
    assert optimization.details["cpu"]["action"] == "insufficient_data"
    assert optimization.details["cpu"]["reason_code"] == "no_samples"


def test_refresh_machine_optimization_raises_cpu_and_ram_targets_to_min(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CPU and RAM optimizations should raise recommendations below the configured minimums."""
    _configure_optimization_settings(monkeypatch, window_size=1, min_cpu=2, max_cpu=8, min_ram_mb=4096, max_ram_mb=32768)

    platform = Platform(name="Optimization Minimum Bounds")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-4",
        hostname="vm-4",
        cpu=1,
        ram_mb=2048,
        disk_mb=80 * 1024,
    )
    cpu_provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 10},
        provisioners=[provisioner],
    )
    ram_provider = MachineProvider(
        platform=platform,
        name="ram",
        type="mock_metric",
        scope="ram",
        enabled=True,
        config={"value": 99},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, cpu_provider, ram_provider])
    db_session.commit()

    db_session.add_all(
        [
            MachineCPUMetric(provider_id=cpu_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=10),
            MachineRAMMetric(provider_id=ram_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=99),
        ]
    )
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimization = db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == machine.id).one()
    assert optimization.target_cpu == 2
    assert optimization.target_ram_mb == 4096
    assert optimization.details["cpu"]["action"] == "scale_up"
    assert optimization.details["cpu"]["reason_code"] == "raised_to_min_cpu"
    assert optimization.details["ram"]["action"] == "scale_up"
    assert optimization.details["ram"]["reason_code"] == "raised_to_min_ram"
    assert optimization.details["ram"]["bounded_target_capacity"] == 4096
    assert optimization.details["ram"]["bounded_target_capacity"] % 1024 == 0


def test_refresh_machine_optimization_keeps_cpu_and_ram_targets_when_target_exceeds_max(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CPU and RAM optimizations should keep current capacity when calculated targets exceed maximums."""
    _configure_optimization_settings(monkeypatch, window_size=1, min_cpu=1, max_cpu=4, min_ram_mb=2048, max_ram_mb=8192)

    platform = Platform(name="Optimization Maximum Bounds")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-4-max",
        hostname="vm-4-max",
        cpu=3,
        ram_mb=4096,
        disk_mb=80 * 1024,
    )
    cpu_provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 99},
        provisioners=[provisioner],
    )
    ram_provider = MachineProvider(
        platform=platform,
        name="ram",
        type="mock_metric",
        scope="ram",
        enabled=True,
        config={"value": 200},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, cpu_provider, ram_provider])
    db_session.commit()

    db_session.add_all(
        [
            MachineCPUMetric(provider_id=cpu_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=99),
            MachineRAMMetric(provider_id=ram_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=200),
        ]
    )
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimization = db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == machine.id).one()
    assert optimization.target_cpu == 3
    assert optimization.target_ram_mb == 4096
    assert optimization.details["cpu"]["action"] == "keep"
    assert optimization.details["cpu"]["reason_code"] == "above_max_cpu"
    assert optimization.details["cpu"]["bounded_target_capacity"] is None
    assert optimization.details["ram"]["action"] == "keep"
    assert optimization.details["ram"]["reason_code"] == "above_max_ram"
    assert optimization.details["ram"]["bounded_target_capacity"] is None


def test_refresh_machine_optimization_never_scales_disk_down(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disk optimizations should stay at keep instead of proposing a downscale."""
    _configure_optimization_settings(monkeypatch, window_size=1)

    platform = Platform(name="Optimization Disk")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-5",
        hostname="vm-5",
        cpu=2,
        ram_mb=4096,
        disk_mb=120 * 1024,
    )
    disk_provider = MachineProvider(
        platform=platform,
        name="disk",
        type="mock_metric",
        scope="disk",
        enabled=True,
        config={"value": 5},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, disk_provider])
    db_session.commit()

    db_session.add(MachineDiskMetric(provider_id=disk_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=5))
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimization = db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == machine.id).one()
    assert optimization.details["disk"]["action"] == "keep"
    assert optimization.target_disk_mb == machine.disk_mb


def test_refresh_machine_optimization_rounds_ram_and_disk_targets_to_gib_steps(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAM and disk recommendations should stay aligned to 1024 MB steps."""
    _configure_optimization_settings(monkeypatch, window_size=1)

    platform = Platform(name="Optimization Capacity Steps")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        external_id="vm-step",
        hostname="vm-step",
        cpu=2,
        ram_mb=4096,
        disk_mb=80 * 1024,
    )
    ram_provider = MachineProvider(
        platform=platform,
        name="ram",
        type="mock_metric",
        scope="ram",
        enabled=True,
        config={"value": 90},
        provisioners=[provisioner],
    )
    disk_provider = MachineProvider(
        platform=platform,
        name="disk",
        type="mock_metric",
        scope="disk",
        enabled=True,
        config={"value": 90},
        provisioners=[provisioner],
    )
    db_session.add_all([machine, ram_provider, disk_provider])
    db_session.commit()

    db_session.add_all(
        [
            MachineRAMMetric(provider_id=ram_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=90),
            MachineDiskMetric(provider_id=disk_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=90),
        ]
    )
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    optimization = db_session.query(MachineOptimization).filter(MachineOptimization.machine_id == machine.id).one()
    assert optimization.target_ram_mb == 6144
    assert optimization.target_disk_mb == 113664
    assert optimization.target_ram_mb % 1024 == 0
    assert optimization.target_disk_mb % 1024 == 0


def test_inventory_refreshes_optimization_when_flavor_changes(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inventory flavor changes should refresh the existing optimization row."""
    _configure_optimization_settings(monkeypatch, window_size=1)

    platform = Platform(name="Inventory Optimization Refresh")
    provisioner = MachineProvisioner(
        platform=platform,
        name="inventory",
        type="mock_inventory",
        enabled=True,
        cron="* * * * *",
        config={"machines": [{"external_id": "vm-6", "hostname": "vm-6", "cpu": 2, "ram_mb": 4096, "disk_mb": 80 * 1024}]},
    )
    cpu_provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        config={"value": 20},
        provisioners=[provisioner],
    )
    db_session.add_all([platform, provisioner, cpu_provider])
    db_session.commit()

    assert run_provisioner_inventory(db_session, provisioner.id) == {"created": 1, "updated": 0, "flavor_changes": 0}
    machine = db_session.query(Machine).filter(Machine.external_id == "vm-6").one()
    db_session.add(MachineCPUMetric(provider_id=cpu_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=20))
    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    provisioner.config = {
        "machines": [{"external_id": "vm-6", "hostname": "vm-6", "cpu": 4, "ram_mb": 4096, "disk_mb": 80 * 1024}]
    }
    db_session.commit()

    assert run_provisioner_inventory(db_session, provisioner.id) == {"created": 0, "updated": 1, "flavor_changes": 1}

    optimizations = (
        db_session.query(MachineOptimization)
        .filter(MachineOptimization.machine_id == machine.id)
        .order_by(MachineOptimization.id.asc())
        .all()
    )
    assert len(optimizations) == 1
    assert optimizations[0].current_cpu == 4
