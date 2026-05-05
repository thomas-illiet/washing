from internal.infra.connectors.base import MachineRecord, MetricRecord
from internal.infra.db.models import Machine, MachineProvider, MachineProvisioner


class MockInventoryProvisioner:
    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        configured = provisioner.config.get("machines")
        if configured:
            return [MachineRecord(**machine) for machine in configured]

        prefix = provisioner.config.get("hostname_prefix", f"platform-{provisioner.platform_id}")
        return [
            MachineRecord(
                external_id=f"{provisioner.id}-vm-1",
                hostname=f"{prefix}-vm-1",
                application_name=provisioner.config.get("application_name"),
                region=provisioner.config.get("region", "eu-west-1"),
                environment=provisioner.config.get("environment", "dev"),
                cpu=float(provisioner.config.get("cpu", 2)),
                ram_gb=float(provisioner.config.get("ram_gb", 8)),
                disk_gb=float(provisioner.config.get("disk_gb", 80)),
                extra={"source": "mock_inventory"},
            )
        ]


class EmptyInventoryProvisioner:
    def discover(self, provisioner: MachineProvisioner) -> list[MachineRecord]:
        return []


class MockMetricCollector:
    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        metric_code = provider.metric_type.code.lower()
        unit = provider.config.get("unit") or provider.metric_type.unit
        default_values = {"cpu": 42.0, "ram": 6.5, "disk": 55.0}
        value = float(provider.config.get("value", default_values.get(metric_code, 1.0)))
        percentile = float(provider.config.get("percentile", 95.0)) if metric_code in {"cpu", "ram"} else None
        usage_type = provider.config.get("usage_type", "used") if metric_code == "disk" else None

        if not machines:
            return []

        samples: list[MetricRecord] = []
        for machine in machines:
            machine_value = provider.config.get("values_by_hostname", {}).get(machine.hostname, value)
            samples.append(
                MetricRecord(
                    value=float(machine_value),
                    unit=unit,
                    percentile=percentile,
                    usage_type=usage_type,
                    machine_id=machine.id,
                    labels={
                        "source": "mock_metric",
                        "hostname": machine.hostname,
                        "environment": machine.environment,
                        "region": machine.region,
                    },
                )
            )
        return samples


class EmptyMetricCollector:
    def collect(self, provider: MachineProvider, machines: list[Machine]) -> list[MetricRecord]:
        return []
