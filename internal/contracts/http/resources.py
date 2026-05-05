"""HTTP request and response schemas."""

from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from croniter import croniter
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, field_validator


Scope = Literal["cpu", "ram", "disk"]
TaskExecutionStatus = Literal["PENDING", "STARTED", "SUCCESS", "FAILURE", "RETRY", "REVOKED"]
ResourceT = TypeVar("ResourceT")
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(BaseModel):
    """Base Pydantic model configured for ORM serialization."""
    model_config = ConfigDict(from_attributes=True, extra="forbid")


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
    name: NonEmptyStr
    description: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PlatformUpdate(ApiModel):
    """Patch payload for a platform."""
    name: NonEmptyStr | None = None
    description: str | None = None
    extra: dict[str, Any] | None = None


class PlatformRead(PlatformCreate):
    """Public representation of a platform."""
    id: int
    created_at: datetime
    updated_at: datetime


class ApplicationCreate(ApiModel):
    """Payload used to create an application."""
    name: NonEmptyStr
    environment: NonEmptyStr
    region: NonEmptyStr
    extra: dict[str, Any] = Field(default_factory=dict)


class ApplicationUpdate(ApiModel):
    """Patch payload for an application."""
    name: NonEmptyStr | None = None
    environment: NonEmptyStr | None = None
    region: NonEmptyStr | None = None
    extra: dict[str, Any] | None = None


class ApplicationRead(ApplicationCreate):
    """Public representation of an application."""
    id: int
    sync_at: datetime | None = None
    sync_scheduled_at: datetime | None = None
    sync_error: str | None = None
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
    name: NonEmptyStr
    enabled: bool = True
    cron: str = "*/5 * * * *"
    token: NonEmptyStr


class CapsuleProvisionerUpdate(CronModel):
    """Patch payload for a Capsule provisioner."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
    enabled: bool | None = None
    cron: str | None = None
    token: NonEmptyStr | None = None


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
    name: NonEmptyStr
    enabled: bool = True
    scope: Scope
    url: AnyHttpUrl
    query: NonEmptyStr
    provisioner_ids: list[int] = Field(default_factory=list)


class PrometheusProviderUpdate(ApiModel):
    """Patch payload for a Prometheus provider."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
    enabled: bool | None = None
    scope: Scope | None = None
    url: AnyHttpUrl | None = None
    query: NonEmptyStr | None = None


class PrometheusProviderRead(ProviderRead):
    """Prometheus provider view with typed query configuration."""
    url: str
    query: str


class DynatraceProviderCreate(ApiModel):
    """Create payload for a Dynatrace provider."""
    platform_id: int
    name: NonEmptyStr
    enabled: bool = True
    scope: Scope
    url: AnyHttpUrl
    token: NonEmptyStr
    provisioner_ids: list[int] = Field(default_factory=list)


class DynatraceProviderUpdate(ApiModel):
    """Patch payload for a Dynatrace provider."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
    enabled: bool | None = None
    scope: Scope | None = None
    url: AnyHttpUrl | None = None
    token: NonEmptyStr | None = None


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
    hostname: NonEmptyStr
    region: NonEmptyStr | None = None
    environment: NonEmptyStr | None = None
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
    hostname: NonEmptyStr | None = None
    region: NonEmptyStr | None = None
    environment: NonEmptyStr | None = None
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
    cpu: float | None = None
    ram_mb: float | None = None
    disk_mb: float | None = None
    changed_at: datetime


class MachineMetricRead(ApiModel):
    """Public representation of one stored machine metric sample."""
    id: int
    provider_id: int
    machine_id: int
    date: date
    value: int


class PaginatedResponse(ApiModel, Generic[ResourceT]):
    """Simple offset/limit paginated response payload."""
    items: list[ResourceT]
    offset: int
    limit: int
    total: int


class TaskEnqueueResponse(ApiModel):
    """Response returned when a Celery task has been enqueued."""
    task_id: str


class TaskExecutionRead(ApiModel):
    """Public representation of one tracked Celery task execution."""
    task_id: str
    task_name: str
    status: TaskExecutionStatus
    resource_type: str | None = None
    resource_id: int | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
