"""Stub connectors used for tests and placeholder integrations."""

from internal.infra.connectors.base import MachineRecord, MetricRecord
from internal.infra.db.models import Machine, MachineProvider, MachineProvisioner


class MockInventoryProvisioner:
    """Inventory connector that emits deterministic fake machines."""
    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        """Return mock inventory records from config or a deterministic fallback."""
        configured = provisioner.config.get("machines")
        if configured:
            records: list[MachineRecord] = []
            for machine in configured:
                payload = dict(machine)
                if "application" not in payload and "application_name" in payload:
                    payload["application"] = payload.pop("application_name")
                records.append(MachineRecord(**payload))
            return records

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
