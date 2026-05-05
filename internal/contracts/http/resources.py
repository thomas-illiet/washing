"""HTTP request and response schemas."""

from datetime import date, datetime
from typing import Any, Literal

from croniter import croniter
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


Scope = Literal["cpu", "ram", "disk"]


def _validate_non_empty(value: str | None, field_name: str) -> str | None:
    """Ensure a required string field is not blank."""
    if value is not None and not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


class ApiModel(BaseModel):
    """Base Pydantic model configured for ORM serialization."""
    model_config = ConfigDict(from_attributes=True)


class CronModel(ApiModel):
    """Base schema that validates cron expressions when present."""
    @field_validator("cron", check_fields=False)
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        """Validate a cron expression accepted by croniter."""
        if value is not None and not croniter.is_valid(value):
            raise ValueError("cron must be a valid cron expression")
        return value


class PlatformCreate(ApiModel):
    """Payload used to create a platform."""
    name: str
    description: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PlatformUpdate(ApiModel):
    """Patch payload for a platform."""
    name: str | None = None
    description: str | None = None
    extra: dict[str, Any] | None = None


class PlatformRead(PlatformCreate):
    """Public representation of a platform."""
    id: int
    created_at: datetime
    updated_at: datetime


class MetricTypeCreate(ApiModel):
    """Payload used to create a metric type."""
    code: str
    name: str
    unit: str | None = None
    description: str | None = None


class MetricTypeUpdate(ApiModel):
    """Patch payload for a metric type."""
    code: str | None = None
    name: str | None = None
    unit: str | None = None
    description: str | None = None


class MetricTypeRead(MetricTypeCreate):
    """Public representation of a metric type."""
    id: int
    created_at: datetime
    updated_at: datetime


class ApplicationCreate(ApiModel):
    """Payload used to create an application."""
    name: str
    environment: str
    region: str
    sync_at: datetime | None = None
    sync_scheduled_at: datetime | None = None
    sync_error: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ApplicationUpdate(ApiModel):
    """Patch payload for an application."""
    name: str | None = None
    environment: str | None = None
    region: str | None = None
    sync_at: datetime | None = None
    sync_scheduled_at: datetime | None = None
    sync_error: str | None = None
    extra: dict[str, Any] | None = None


class ApplicationRead(ApplicationCreate):
    """Public representation of an application."""
    id: int
    created_at: datetime
    updated_at: datetime


class ProvisionerRead(CronModel):
    """Generic provisioner view without typed config fields."""
    id: int
    platform_id: int
    name: str
    type: str
    enabled: bool
    cron: str
    last_scheduled_at: datetime | None = None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class CapsuleProvisionerCreate(CronModel):
    """Create payload for a Capsule provisioner."""
    platform_id: int
    name: str
    enabled: bool = True
    cron: str = "*/5 * * * *"
    token: str

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        """Reject blank provisioner tokens."""
        return _validate_non_empty(value, "token") or value


class CapsuleProvisionerUpdate(CronModel):
    """Patch payload for a Capsule provisioner."""
    platform_id: int | None = None
    name: str | None = None
    enabled: bool | None = None
    cron: str | None = None
    token: str | None = None

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str | None) -> str | None:
        """Reject blank provisioner tokens when provided."""
        return _validate_non_empty(value, "token")


class CapsuleProvisionerRead(ProvisionerRead):
    """Capsule provisioner view exposing secret presence only."""
    has_token: bool


class DynatraceProvisionerCreate(CapsuleProvisionerCreate):
    """Create payload for a Dynatrace provisioner."""
    url: AnyHttpUrl


class DynatraceProvisionerUpdate(CapsuleProvisionerUpdate):
    """Patch payload for a Dynatrace provisioner."""
    url: AnyHttpUrl | None = None


class DynatraceProvisionerRead(ProvisionerRead):
    """Dynatrace provisioner view with visible URL and hidden token."""
    url: str
    has_token: bool


class ProviderRead(ApiModel):
    """Generic provider view without exposing raw config storage."""
    id: int
    platform_id: int
    name: str
    type: str
    scope: Scope
    enabled: bool
    provisioner_ids: list[int]
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class PrometheusProviderCreate(ApiModel):
    """Create payload for a Prometheus provider."""
    platform_id: int
    name: str
    enabled: bool = True
    scope: Scope
    url: AnyHttpUrl
    query: str
    provisioner_ids: list[int] = Field(default_factory=list)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        """Reject blank Prometheus queries."""
        return _validate_non_empty(value, "query") or value


class PrometheusProviderUpdate(ApiModel):
    """Patch payload for a Prometheus provider."""
    platform_id: int | None = None
    name: str | None = None
    enabled: bool | None = None
    scope: Scope | None = None
    url: AnyHttpUrl | None = None
    query: str | None = None
    provisioner_ids: list[int] | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str | None) -> str | None:
        """Reject blank Prometheus queries when provided."""
        return _validate_non_empty(value, "query")


class PrometheusProviderRead(ProviderRead):
    """Prometheus provider view with typed query configuration."""
    url: str
    query: str


class DynatraceProviderCreate(ApiModel):
    """Create payload for a Dynatrace provider."""
    platform_id: int
    name: str
    enabled: bool = True
    scope: Scope
    url: AnyHttpUrl
    token: str
    provisioner_ids: list[int] = Field(default_factory=list)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        """Reject blank provider tokens."""
        return _validate_non_empty(value, "token") or value


class DynatraceProviderUpdate(ApiModel):
    """Patch payload for a Dynatrace provider."""
    platform_id: int | None = None
    name: str | None = None
    enabled: bool | None = None
    scope: Scope | None = None
    url: AnyHttpUrl | None = None
    token: str | None = None
    provisioner_ids: list[int] | None = None

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str | None) -> str | None:
        """Reject blank provider tokens when provided."""
        return _validate_non_empty(value, "token")


class DynatraceProviderRead(ProviderRead):
    """Dynatrace provider view with visible URL and hidden token."""
    url: str
    has_token: bool


class MachineCreate(ApiModel):
    """Payload used to create a machine."""
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
    """Patch payload for a machine."""
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
    """Public representation of a machine."""
    id: int
    created_at: datetime
    updated_at: datetime


class MachineFlavorHistoryRead(ApiModel):
    """Public representation of one machine flavor change."""
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
    """Public representation of one stored metric sample."""
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
    """Response returned when a Celery task has been enqueued."""
    task_id: str
