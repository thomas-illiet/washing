from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.db.models import Machine, MachineProvider, MachineProvisioner


@dataclass(frozen=True)
class MachineRecord:
    external_id: str | None
    hostname: str
    application_id: int | None = None
    application_name: str | None = None
    region: str | None = None
    environment: str | None = None
    cpu: float | None = None
    ram_gb: float | None = None
    disk_gb: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MetricRecord:
    value: float
    unit: str | None = None
    percentile: float | None = None
    usage_type: str | None = None
    machine_id: int | None = None
    machine_external_id: str | None = None
    hostname: str | None = None
    labels: dict = field(default_factory=dict)
    collected_at: datetime | None = None


class MachineProvisionerConnector(Protocol):
    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        """Return machine inventory records for a provisioner."""


class MetricCollectorConnector(Protocol):
    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        """Return metric samples for the provider and scoped machines."""
