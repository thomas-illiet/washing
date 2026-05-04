from datetime import date, datetime
from typing import Any

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CronModel(ApiModel):
    @field_validator("cron", check_fields=False)
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        if value is not None and not croniter.is_valid(value):
            raise ValueError("cron must be a valid cron expression")
        return value


class PlatformCreate(ApiModel):
    name: str
    description: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PlatformUpdate(ApiModel):
    name: str | None = None
    description: str | None = None
    extra: dict[str, Any] | None = None


class PlatformRead(PlatformCreate):
    id: int
    created_at: datetime
    updated_at: datetime


class MetricTypeCreate(ApiModel):
    code: str
    name: str
    unit: str | None = None
    description: str | None = None


class MetricTypeUpdate(ApiModel):
    code: str | None = None
    name: str | None = None
    unit: str | None = None
    description: str | None = None


class MetricTypeRead(MetricTypeCreate):
    id: int
    created_at: datetime
    updated_at: datetime


class ApplicationCreate(ApiModel):
    name: str
    environment: str
    region: str
    sync_at: datetime | None = None
    sync_scheduled_at: datetime | None = None
    sync_error: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ApplicationUpdate(ApiModel):
    name: str | None = None
    environment: str | None = None
    region: str | None = None
    sync_at: datetime | None = None
    sync_scheduled_at: datetime | None = None
    sync_error: str | None = None
    extra: dict[str, Any] | None = None


class ApplicationRead(ApplicationCreate):
    id: int
    created_at: datetime
    updated_at: datetime


class ProvisionerCreate(CronModel):
    platform_id: int
    name: str
    type: str = "mock_inventory"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    cron: str = "*/5 * * * *"


class ProvisionerUpdate(CronModel):
    platform_id: int | None = None
    name: str | None = None
    type: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    cron: str | None = None


class ProvisionerRead(ProvisionerCreate):
    id: int
    last_scheduled_at: datetime | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ProviderCreate(CronModel):
    platform_id: int
    metric_type_id: int
    name: str
    type: str = "mock_metric"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    cron: str = "*/5 * * * *"
    provisioner_ids: list[int] = Field(default_factory=list)


class ProviderUpdate(CronModel):
    platform_id: int | None = None
    metric_type_id: int | None = None
    name: str | None = None
    type: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    cron: str | None = None


class ProviderRead(ApiModel):
    id: int
    platform_id: int
    metric_type_id: int
    name: str
    type: str
    config: dict[str, Any]
    enabled: bool
    cron: str
    provisioner_ids: list[int]
    last_scheduled_at: datetime | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class MachineCreate(ApiModel):
    platform_id: int
    application_id: int | None = None
    source_provisioner_id: int | None = None
    external_id: str | None = None
    hostname: str
    region: str | None = None
    environment: str | None = None
    cpu: float | None = None
    ram_gb: float | None = None
    disk_gb: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MachineUpdate(ApiModel):
    platform_id: int | None = None
    application_id: int | None = None
    source_provisioner_id: int | None = None
    external_id: str | None = None
    hostname: str | None = None
    region: str | None = None
    environment: str | None = None
    cpu: float | None = None
    ram_gb: float | None = None
    disk_gb: float | None = None
    extra: dict[str, Any] | None = None


class MachineRead(MachineCreate):
    id: int
    created_at: datetime
    updated_at: datetime


class MachineFlavorHistoryRead(ApiModel):
    id: int
    machine_id: int
    source_provisioner_id: int | None = None
    previous_cpu: float | None = None
    previous_ram_gb: float | None = None
    previous_disk_gb: float | None = None
    new_cpu: float | None = None
    new_ram_gb: float | None = None
    new_disk_gb: float | None = None
    changed_at: datetime


class MetricRead(ApiModel):
    id: int
    provider_id: int
    machine_id: int
    metric_date: date
    value: float
    percentile: float | None = None
    usage_type: str | None = None
    unit: str | None = None
    labels: dict[str, Any]
    collected_at: datetime
    created_at: datetime
    updated_at: datetime


class TaskEnqueueResponse(ApiModel):
    task_id: str
