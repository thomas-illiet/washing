"""Mock machine provisioner connectors."""

import json
import re
from pathlib import Path

from internal.domain import (
    normalize_application_code,
    normalize_dimension,
    normalize_external_id,
    normalize_hostname,
)
from internal.infra.connectors.base import MachineRecord
from internal.infra.db.models import MachineProvisioner

DEFAULT_MOCK_PRESET = "single-vm"
_MOCK_PRESET_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MACHINE_RECORD_FIELDS = frozenset(MachineRecord.__dataclass_fields__)


def get_mock_presets_dir() -> Path:
    """Return the repository directory that stores mock inventory presets."""
    return Path(__file__).resolve().parents[4] / "mock"


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
        payload["external_id"] = normalize_external_id(payload.get("external_id"))
        payload["hostname"] = normalize_hostname(payload.get("hostname")) or payload.get("hostname")
        payload["application"] = normalize_application_code(payload.get("application"))
        payload["region"] = normalize_dimension(payload.get("region"))
        payload["environment"] = normalize_dimension(payload.get("environment"))
        payload.setdefault("extra", {})
        records.append(MachineRecord(**{key: value for key, value in payload.items() if key in _MACHINE_RECORD_FIELDS}))
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
        ram_mb = provisioner.config.get("ram_mb", 8 * 1024)
        disk_mb = provisioner.config.get("disk_mb", 80 * 1024)
        return [
            MachineRecord(
                external_id=normalize_external_id(f"{provisioner.id}-vm-1"),
                hostname=normalize_hostname(f"{prefix}-vm-1") or f"{prefix}-vm-1",
                application=normalize_application_code(
                    provisioner.config.get("application") or provisioner.config.get("application_name")
                ),
                region=normalize_dimension(provisioner.config.get("region", "EU-WEST-1")),
                environment=normalize_dimension(provisioner.config.get("environment", "DEV")),
                cpu=float(provisioner.config.get("cpu", 2)),
                ram_mb=float(ram_mb) if ram_mb is not None else None,
                disk_mb=float(disk_mb) if disk_mb is not None else None,
                extra={"source": "mock_inventory"},
            )
        ]
