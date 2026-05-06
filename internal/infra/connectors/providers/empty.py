"""Placeholder metric provider connectors."""

from internal.infra.connectors.base import MetricRecord
from internal.infra.db.models import Machine, MachineProvider


class EmptyMetricCollector:
    """Placeholder metric connector that returns no samples."""

    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        """Return no metrics for placeholder integrations."""
        return []
