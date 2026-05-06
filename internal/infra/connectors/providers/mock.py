"""Mock metric provider connectors."""

from internal.domain import normalize_hostname
from internal.infra.connectors.base import MetricRecord
from internal.infra.db.models import Machine, MachineProvider


class MockMetricCollector:
    """Metric connector that emits deterministic fake metric samples."""

    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        """Produce deterministic mock metrics for the scoped machines."""
        metric_code = provider.scope.lower()
        default_values = {"cpu": 42.0, "ram": 6.5, "disk": 55.0}
        value = float(provider.config.get("value", default_values.get(metric_code, 1.0)))

        if not machines:
            return []

        values_by_hostname = {
            normalize_hostname(hostname) or hostname: configured_value
            for hostname, configured_value in provider.config.get("values_by_hostname", {}).items()
        }
        samples: list[MetricRecord] = []
        for machine in machines:
            machine_value = values_by_hostname.get(normalize_hostname(machine.hostname) or machine.hostname, value)
            samples.append(
                MetricRecord(
                    value=float(machine_value),
                    machine_id=machine.id,
                )
            )
        return samples
