"""Placeholder machine provisioner connectors."""

from internal.infra.connectors.base import MachineRecord
from internal.infra.db.models import MachineProvisioner


class EmptyInventoryProvisioner:
    """Placeholder inventory connector that returns no machines."""

    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        """Return no inventory records for placeholder integrations."""
        return []
