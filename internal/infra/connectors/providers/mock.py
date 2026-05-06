"""Mock metric provider connectors."""

import random

from internal.domain import normalize_hostname
from internal.infra.connectors.base import MetricRecord
from internal.infra.db.models import Machine, MachineProvider


RANDOM_VALUE_RANGE_BY_METRIC = {
    "cpu": (0, 100),
    "ram": (0, 100),
    "disk": (0, 100),
}


class MockMetricCollector:
    """Metric connector that emits fake metric samples for one provider scope."""

    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        """Produce one metric sample per machine for the provider scope."""
        metric_code = provider.scope.lower()
        configured_value = provider.config.get("value")

        if not machines:
            return []

        values_by_hostname = {
            normalize_hostname(hostname) or hostname: configured_value
            for hostname, configured_value in provider.config.get("values_by_hostname", {}).items()
        }
        samples: list[MetricRecord] = []
        for machine in machines:
            hostname = normalize_hostname(machine.hostname) or machine.hostname
            machine_value = values_by_hostname.get(hostname)
            if machine_value is None:
                machine_value = configured_value
            if machine_value is None:
                machine_value = self._random_metric_value(metric_code)
            samples.append(
                MetricRecord(
                    value=float(machine_value),
                    machine_id=machine.id,
                )
            )
        return samples

    @staticmethod
    def _random_metric_value(metric_code: str) -> float:
        """Return a bounded random fallback for the requested metric scope."""
        lower_bound, upper_bound = RANDOM_VALUE_RANGE_BY_METRIC.get(metric_code, (0, 100))
        return float(random.randint(lower_bound, upper_bound))
