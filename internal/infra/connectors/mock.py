"""Stub connectors used for tests and placeholder integrations."""

import json
import re
from pathlib import Path

from internal.infra.connectors.base import MachineRecord, MetricRecord
from internal.infra.db.models import Machine, MachineProvider, MachineProvisioner

DEFAULT_MOCK_PRESET = "single-vm"
_MOCK_PRESET_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def get_mock_presets_dir() -> Path:
    """Return the repository directory that stores mock inventory presets."""
    return Path(__file__).resolve().parents[3] / "mock"


def validate_mock_preset_name(preset: str) -> str:
    """Reject preset names that could escape the dedicated mock directory."""
    if not _MOCK_PRESET_NAME_RE.fullmatch(preset):
        raise ValueError(f"invalid mock preset: {preset}")
    return preset


def resolve_mock_preset_path(preset: str) -> Path:
    """Resolve a mock preset to its JSON file inside the repository."""
    preset_name = validate_mock_preset_name(preset)
    path = get_mock_presets_dir() / f"{preset_name}.json"
    if not path.is_file():
        raise ValueError(f"unknown mock preset: {preset_name}")
    return path


def list_mock_presets() -> list[str]:
    """List the preset names currently available in the repository."""
    presets_dir = get_mock_presets_dir()
    if not presets_dir.exists():
        return []
    return sorted(
        path.stem
        for path in presets_dir.glob("*.json")
        if path.is_file() and _MOCK_PRESET_NAME_RE.fullmatch(path.stem)
    )


def _machine_records_from_configured_machines(configured: list[dict]) -> list[MachineRecord]:
    """Build normalized machine records from a JSON-style machine list."""
    records: list[MachineRecord] = []
    for machine in configured:
        payload = dict(machine)
        if "application" not in payload and "application_name" in payload:
            payload["application"] = payload.pop("application_name")
        payload.setdefault("extra", {})
        records.append(MachineRecord(**payload))
    return records


def load_mock_preset_records(preset: str) -> list[MachineRecord]:
    """Load one repository-backed mock preset and convert it to machine records."""
    with resolve_mock_preset_path(preset).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"invalid mock preset payload: {preset}")
    configured = payload.get("machines")
    if not isinstance(configured, list):
        raise ValueError(f"invalid mock preset payload: {preset}")
    return _machine_records_from_configured_machines(configured)


class MockInventoryProvisioner:
    """Inventory connector that emits deterministic fake machines."""
    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        """Return mock inventory records from config or a deterministic fallback."""
        preset = provisioner.config.get("preset")
        if preset is not None:
            return load_mock_preset_records(str(preset))

        configured = provisioner.config.get("machines")
        if configured is not None:
            if not isinstance(configured, list):
                raise ValueError("invalid mock inventory config: machines must be a list")
            return _machine_records_from_configured_machines(configured)

        prefix = provisioner.config.get("hostname_prefix", f"platform-{provisioner.platform_id}")
        return [
            MachineRecord(
                external_id=f"{provisioner.id}-vm-1",
                hostname=f"{prefix}-vm-1",
                application=provisioner.config.get("application") or provisioner.config.get("application_name"),
                region=provisioner.config.get("region", "eu-west-1"),
                environment=provisioner.config.get("environment", "dev"),
                cpu=float(provisioner.config.get("cpu", 2)),
                ram_gb=float(provisioner.config.get("ram_gb", 8)),
                disk_gb=float(provisioner.config.get("disk_gb", 80)),
                extra={"source": "mock_inventory"},
            )
        ]


class EmptyInventoryProvisioner:
    """Placeholder inventory connector that returns no machines."""
    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        """Return no inventory records for placeholder integrations."""
        return []


class MockMetricCollector:
    """Metric connector that emits deterministic fake metric samples."""
    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        """Produce deterministic mock metrics for the scoped machines."""
        metric_code = provider.scope.lower()
        default_values = {"cpu": 42.0, "ram": 6.5, "disk": 55.0}
        value = float(provider.config.get("value", default_values.get(metric_code, 1.0)))

        if not machines:
            return []

        samples: list[MetricRecord] = []
        for machine in machines:
            machine_value = provider.config.get("values_by_hostname", {}).get(machine.hostname, value)
            samples.append(
                MetricRecord(
                    value=float(machine_value),
                    machine_id=machine.id,
                )
            )
        return samples


class EmptyMetricCollector:
    """Placeholder metric connector that returns no samples."""
    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        """Return no metrics for placeholder integrations."""
        return []
