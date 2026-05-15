"""HTTP request and response schemas."""

from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from internal.domain.cron import validate_cron_expression
from internal.infra.security import sanitize_operational_error, sanitize_task_result


Scope = Literal["cpu", "ram", "disk"]
TaskExecutionStatus = Literal["PENDING", "STARTED", "SUCCESS", "FAILURE", "RETRY", "REVOKED"]
ApplicationSyncType = Literal["inventory_discovery", "metrics"]
MachineOptimizationStatus = Literal["ready", "partial", "error"]
MachineOptimizationAction = Literal["scale_up", "scale_down", "mixed", "keep", "insufficient_data", "unavailable"]
MachineOptimizationScopeStatus = Literal[
    "ok",
    "missing_provider",
    "ambiguous_provider",
    "insufficient_data",
    "missing_current_capacity",
]
MachineOptimizationScopeAction = Literal["scale_up", "scale_down", "keep", "insufficient_data", "unavailable"]
DiscoveryRecordType = Literal["catalog", "application", "machine", "optimization"]
ResourceT = TypeVar("ResourceT")
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


# Shared schema building blocks.
class ApiModel(BaseModel):
    """Base Pydantic model configured for ORM serialization."""
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class CronModel(ApiModel):
    """Base schema that validates cron expressions when present."""
    @field_validator("cron", check_fields=False)
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        """Validate a cron expression through the shared domain helper."""
        if value is not None:
            return validate_cron_expression(value)
        return value


# Platform and application resources.
class PlatformCreate(ApiModel):
    """Payload used to create a platform."""
    name: NonEmptyStr
    description: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PlatformUpdate(ApiModel):
    """Patch payload for a platform."""
    description: str | None = None
    extra: dict[str, Any] | None = None


class PlatformRead(PlatformCreate):
    """Public representation of a platform."""
    id: int
    created_at: datetime
    updated_at: datetime


class PlatformSummaryRead(ApiModel):
    """Aggregated operational summary for one platform."""
    platform_id: int
    machines: int
    applications: int
    providers: int
    enabled_providers: int
    provisioners: int
    enabled_provisioners: int
    current_optimizations: int
    current_optimizations_by_status: dict[MachineOptimizationStatus, int] = Field(default_factory=dict)
    current_optimizations_by_action: dict[MachineOptimizationAction, int] = Field(default_factory=dict)


class ApplicationRead(ApiModel):
    """Public representation of an application."""
    id: int
    name: NonEmptyStr
    environment: NonEmptyStr
    region: NonEmptyStr
    sync_at: datetime | None = None
    sync_scheduled_at: datetime | None = None
    sync_error: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("sync_error", mode="before")
    @classmethod
    def sanitize_sync_error(cls, value: str | None) -> str | None:
        """Keep exposed sync errors inside the bounded safe vocabulary."""
        return sanitize_operational_error(value)


# Provisioner resources.
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

    @field_validator("last_error", mode="before")
    @classmethod
    def sanitize_last_error(cls, value: str | None) -> str | None:
        """Keep exposed provisioner errors inside the bounded safe vocabulary."""
        return sanitize_operational_error(value)


class CapsuleProvisionerCreate(CronModel):
    """Create payload for a Capsule provisioner."""
    platform_id: int
    name: NonEmptyStr
    cron: str = "*/5 * * * *"
    token: NonEmptyStr
    parameters: dict[str, str] = Field(default_factory=dict)


class CapsuleProvisionerUpdate(CronModel):
    """Patch payload for a Capsule provisioner."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
    cron: str | None = None
    token: NonEmptyStr | None = None
    parameters: dict[str, str] | None = None


class CapsuleProvisionerRead(ProvisionerRead):
    """Capsule provisioner view exposing editable non-secret config."""
    has_token: bool
    parameters: dict[str, str] = Field(default_factory=dict)


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


class MockProvisionerCreate(CronModel):
    """Create payload for a development-only mock provisioner."""
    platform_id: int
    name: NonEmptyStr
    cron: str = "*/5 * * * *"
    preset: NonEmptyStr = "single-vm"


class MockProvisionerUpdate(CronModel):
    """Patch payload for a development-only mock provisioner."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
    cron: str | None = None
    preset: NonEmptyStr | None = None


class MockProvisionerRead(ProvisionerRead):
    """Mock provisioner view exposing the selected fake-data preset."""
    preset: str


# Provider resources.
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

    @field_validator("last_error", mode="before")
    @classmethod
    def sanitize_last_error(cls, value: str | None) -> str | None:
        """Keep exposed provider errors inside the bounded safe vocabulary."""
        return sanitize_operational_error(value)


class PrometheusProviderCreate(ApiModel):
    """Create payload for a Prometheus provider."""
    platform_id: int
    name: NonEmptyStr
    scope: Scope
    url: AnyHttpUrl
    query: NonEmptyStr


class PrometheusProviderUpdate(ApiModel):
    """Patch payload for a Prometheus provider."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
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
    scope: Scope
    url: AnyHttpUrl
    token: NonEmptyStr
    provisioner_ids: list[int] = Field(default_factory=list)


class DynatraceProviderUpdate(ApiModel):
    """Patch payload for a Dynatrace provider."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
    scope: Scope | None = None
    url: AnyHttpUrl | None = None
    token: NonEmptyStr | None = None


class DynatraceProviderRead(ProviderRead):
    """Dynatrace provider view with visible URL and hidden token."""
    url: str
    has_token: bool


class MockProviderCreate(ApiModel):
    """Create payload for a development-only mock metric provider."""
    platform_id: int
    name: NonEmptyStr
    scope: Scope


class MockProviderUpdate(ApiModel):
    """Patch payload for a development-only mock metric provider."""
    platform_id: int | None = None
    name: NonEmptyStr | None = None
    scope: Scope | None = None


class MockProviderRead(ApiModel):
    """Mock provider view exposing only shared random-provider metadata."""
    id: int
    platform_id: int
    name: str
    type: str
    scope: Scope
    enabled: bool
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("last_error", mode="before")
    @classmethod
    def sanitize_last_error(cls, value: str | None) -> str | None:
        """Keep exposed provider errors inside the bounded safe vocabulary."""
        return sanitize_operational_error(value)


# Machine and metric resources.
class MachineCreate(ApiModel):
    """Payload used to create a machine."""
    platform_id: int
    application: NonEmptyStr | None = None
    source_provisioner_id: int | None = None
    external_id: str | None = None
    hostname: NonEmptyStr
    region: NonEmptyStr | None = None
    environment: NonEmptyStr | None = None
    cpu: float | None = None
    ram_mb: float | None = None
    disk_mb: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class MachineUpdate(ApiModel):
    """Patch payload for a machine."""
    platform_id: int | None = None
    application: NonEmptyStr | None = None
    source_provisioner_id: int | None = None
    external_id: str | None = None
    hostname: NonEmptyStr | None = None
    region: NonEmptyStr | None = None
    environment: NonEmptyStr | None = None
    cpu: float | None = None
    ram_mb: float | None = None
    disk_mb: float | None = None
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


class MachineMetricLatestRead(ApiModel):
    """Latest stored metric sample for each machine metric scope."""
    cpu: MachineMetricRead | None = None
    ram: MachineMetricRead | None = None
    disk: MachineMetricRead | None = None


class MachineOptimizationResourceRead(ApiModel):
    """Public resource recommendation inside a stored optimization."""
    status: MachineOptimizationScopeStatus
    action: MachineOptimizationScopeAction
    current: float | None = None
    recommended: float | None = None
    unit: Literal["cores", "mb"]
    utilization_percent: float | None = None
    reason: str


class MachineOptimizationRead(ApiModel):
    """Public representation of one machine optimization."""
    id: int
    machine_id: int
    status: MachineOptimizationStatus
    action: MachineOptimizationAction
    computed_at: datetime
    resources: dict[Scope, MachineOptimizationResourceRead]
    created_at: datetime
    updated_at: datetime


# Discovery and assistant-friendly resources.
class BoundedResponse(ApiModel, Generic[ResourceT]):
    """Bounded list response that avoids exposing pagination controls."""
    items: list[ResourceT]
    total: int
    returned: int
    truncated: bool


class DiscoveryCatalogRead(ApiModel):
    """Top-level inventory catalog for assistant discovery."""
    platforms: list[PlatformRead]
    environments: list[str]
    regions: list[str]
    metric_types: list[Scope]
    optimization_statuses: list[MachineOptimizationStatus]
    optimization_actions: list[MachineOptimizationAction]
    totals: dict[str, int]


class ApplicationSummaryRead(ApiModel):
    """Assistant-friendly application summary."""
    application: ApplicationRead
    machine_count: int
    platform_ids: list[int]
    current_optimization_count: int
    current_optimizations_by_status: dict[MachineOptimizationStatus, int] = Field(default_factory=dict)
    current_optimizations_by_action: dict[MachineOptimizationAction, int] = Field(default_factory=dict)


class ApplicationOverviewRead(ApiModel):
    """Complete assistant context for one application projection row."""
    application: ApplicationRead
    machine_count: int
    platform_ids: list[int]
    current_optimization_count: int
    current_optimizations_by_status: dict[MachineOptimizationStatus, int] = Field(default_factory=dict)
    current_optimizations_by_action: dict[MachineOptimizationAction, int] = Field(default_factory=dict)
    machines: BoundedResponse[MachineRead]
    current_optimizations: BoundedResponse[MachineOptimizationRead]


class MachineContextRead(ApiModel):
    """Complete assistant context for one machine."""
    machine: MachineRead
    platform: PlatformRead | None = None
    application: ApplicationRead | None = None
    latest_metrics: MachineMetricLatestRead
    current_optimization: MachineOptimizationRead | None = None


class OptimizationRecommendationRead(ApiModel):
    """Current optimization with its machine and ownership context."""
    optimization: MachineOptimizationRead
    machine: MachineRead
    platform: PlatformRead | None = None
    application: ApplicationRead | None = None


class DiscoveryRecordRead(ApiModel):
    """Fetchable text record for MCP search/fetch compatibility."""
    id: str
    type: DiscoveryRecordType
    title: str
    text: str
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# Shared envelopes and async task resources.
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

    @field_validator("result", mode="before")
    @classmethod
    def sanitize_result(cls, value: object) -> dict[str, Any] | None:
        """Expose only the safe subset of stored task result keys."""
        return sanitize_task_result(value)

    @field_validator("error", mode="before")
    @classmethod
    def sanitize_error(cls, value: str | None) -> str | None:
        """Keep exposed task errors inside the bounded safe vocabulary."""
        return sanitize_operational_error(value)
