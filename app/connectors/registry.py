from app.connectors.base import MachineProvisionerConnector, MetricCollectorConnector
from app.connectors.mock import MockInventoryProvisioner, MockMetricCollector


METRIC_COLLECTORS: dict[str, MetricCollectorConnector] = {
    "mock": MockMetricCollector(),
    "mock_metric": MockMetricCollector(),
}

MACHINE_PROVISIONERS: dict[str, MachineProvisionerConnector] = {
    "mock": MockInventoryProvisioner(),
    "mock_inventory": MockInventoryProvisioner(),
}


def get_metric_collector(connector_type: str) -> MetricCollectorConnector:
    try:
        return METRIC_COLLECTORS[connector_type]
    except KeyError as exc:
        raise ValueError(f"unsupported metric collector type: {connector_type}") from exc


def get_machine_provisioner(connector_type: str) -> MachineProvisionerConnector:
    try:
        return MACHINE_PROVISIONERS[connector_type]
    except KeyError as exc:
        raise ValueError(f"unsupported machine provisioner type: {connector_type}") from exc
