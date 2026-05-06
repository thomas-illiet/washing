"""Connector protocols and shared payload shapes."""

from dataclasses import dataclass, field
from datetime import date as date_value
from typing import Protocol

from internal.infra.db.models import Machine, MachineProvider, MachineProvisioner


@dataclass(frozen=True)
class MachineRecord:
    """Normalized inventory payload returned by provisioner connectors."""
    external_id: str | None
    hostname: str
    application: str | None = None
    region: str | None = None
    environment: str | None = None
    cpu: float | None = None
    ram_mb: float | None = None
    disk_mb: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MetricRecord:
    """Normalized metric sample returned by provider connectors."""
    value: float
    date: date_value | None = None
    machine_id: int | None = None
    machine_external_id: str | None = None
    hostname: str | None = None


class MachineProvisionerConnector(Protocol):
    """Protocol implemented by machine inventory connectors."""
    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        """Return machine inventory records for a provisioner."""


class MetricCollectorConnector(Protocol):
    """Protocol implemented by metric collection connectors."""
    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        """Return metric samples for the provider and scoped machines."""
