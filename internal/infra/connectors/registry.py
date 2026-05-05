"""Connector registry lookups."""

from internal.infra.connectors.base import MachineProvisionerConnector, MetricCollectorConnector
from internal.infra.connectors.mock import (
    EmptyInventoryProvisioner,
    EmptyMetricCollector,
    MockInventoryProvisioner,
    MockMetricCollector,
)


METRIC_COLLECTORS: dict[str, MetricCollectorConnector] = {
    "mock": MockMetricCollector(),
    "mock_metric": MockMetricCollector(),
    "prometheus": EmptyMetricCollector(),
    "dynatrace": EmptyMetricCollector(),
}

MACHINE_PROVISIONERS: dict[str, MachineProvisionerConnector] = {
    "mock": MockInventoryProvisioner(),
    "mock_inventory": MockInventoryProvisioner(),
    "capsule": EmptyInventoryProvisioner(),
    "dynatrace": EmptyInventoryProvisioner(),
}


def get_metric_collector(connector_type: str) -> MetricCollectorConnector:
    """Resolve the metric collector registered for a provider type."""
    try:
        return METRIC_COLLECTORS[connector_type]
    except KeyError as exc:
        raise ValueError(f"unsupported metric collector type: {connector_type}") from exc


def get_machine_provisioner(connector_type: str) -> MachineProvisionerConnector:
    """Resolve the provisioner connector registered for a provisioner type."""
    try:
        return MACHINE_PROVISIONERS[connector_type]
    except KeyError as exc:
        raise ValueError(f"unsupported machine provisioner type: {connector_type}") from exc
