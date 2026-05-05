"""SQLAlchemy ORM models for the application domain."""

from datetime import date as date_value, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from internal.infra.db.base import Base, EncryptedJSONType, JSONType, JsonDict, TimestampMixin, utcnow


class Platform(TimestampMixin, Base):
    """Top-level platform grouping machines, providers, and provisioners."""
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[JsonDict] = mapped_column(JSONType, default=dict, nullable=False)

    machines: Mapped[list["Machine"]] = relationship(back_populates="platform", cascade="all, delete-orphan")
    providers: Mapped[list["MachineProvider"]] = relationship(back_populates="platform", cascade="all, delete-orphan")
    provisioners: Mapped[list["MachineProvisioner"]] = relationship(
        back_populates="platform",
        cascade="all, delete-orphan",
    )


class Application(TimestampMixin, Base):
    """Business application attached to machines for inventory mapping."""
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("name", "environment", "region", name="uq_applications_name_environment_region"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sync_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sync_error: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[JsonDict] = mapped_column(JSONType, default=dict, nullable=False)

    machines: Mapped[list["Machine"]] = relationship(back_populates="application")


class CeleryTaskExecution(Base):
    """Audit row describing one tracked Celery task execution."""
    __tablename__ = "celery_task_executions"
    __table_args__ = (
        Index("ix_celery_task_executions_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), index=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    result: Mapped[JsonDict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)


class MachineProviderProvisioner(Base):
    """Association table linking providers to provisioners."""
    __tablename__ = "machine_provider_provisioners"
    __table_args__ = (
        UniqueConstraint("provider_id", "provisioner_id", name="uq_machine_provider_provisioners_pair"),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("machine_providers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provisioner_id: Mapped[int] = mapped_column(
        ForeignKey("machine_provisioners.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MachineProvisioner(TimestampMixin, Base):
    """Inventory integration able to discover machines."""
    __tablename__ = "machine_provisioners"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="mock_inventory")
    config: Mapped[JsonDict] = mapped_column(EncryptedJSONType(), default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    cron: Mapped[str] = mapped_column(String(64), default="*/5 * * * *", nullable=False)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    platform: Mapped["Platform"] = relationship(back_populates="provisioners")
    providers: Mapped[list["MachineProvider"]] = relationship(
        secondary="machine_provider_provisioners",
        back_populates="provisioners",
    )
    machines: Mapped[list["Machine"]] = relationship(back_populates="source_provisioner")

    __table_args__ = (UniqueConstraint("platform_id", "name", name="uq_machine_provisioners_platform_name"),)

    @validates("providers")
    def validate_provider_type_uniqueness(self, _key: str, provider: "MachineProvider") -> "MachineProvider":
        """Reject attaching multiple providers of the same type."""
        conflict = find_provider_type_conflict(
            self,
            provider.type,
            provider_id=provider.id,
            candidate_provider=provider,
        )
        if conflict is not None:
            raise ValueError(PROVISIONER_PROVIDER_TYPE_CONFLICT_DETAIL)
        return provider


class MachineProvider(TimestampMixin, Base):
    """Metric integration able to collect samples for machines."""
    __tablename__ = "machine_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="mock_metric")
    scope: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    config: Mapped[JsonDict] = mapped_column(EncryptedJSONType(), default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    platform: Mapped["Platform"] = relationship(back_populates="providers")
    provisioners: Mapped[list["MachineProvisioner"]] = relationship(
        secondary="machine_provider_provisioners",
        back_populates="providers",
    )

    __table_args__ = (UniqueConstraint("platform_id", "name", name="uq_machine_providers_platform_name"),)

    @property
    def provisioner_ids(self) -> list[int]:
        """Expose attached provisioner ids for HTTP serialization."""
        return [provisioner.id for provisioner in self.provisioners]

    @validates("provisioners")
    def validate_provisioner_provider_type_uniqueness(
        self,
        _key: str,
        provisioner: MachineProvisioner,
    ) -> MachineProvisioner:
        """Reject attaching this provider to a provisioner that already has its type."""
        conflict = find_provider_type_conflict(
            provisioner,
            self.type,
            provider_id=self.id,
            candidate_provider=self,
        )
        if conflict is not None:
            raise ValueError(PROVISIONER_PROVIDER_TYPE_CONFLICT_DETAIL)
        return provisioner


class Machine(TimestampMixin, Base):
    """Persisted machine inventory record."""
    __tablename__ = "machines"
    __table_args__ = (
        UniqueConstraint("platform_id", "hostname", name="uq_machines_platform_hostname"),
        UniqueConstraint("source_provisioner_id", "external_id", name="uq_machines_provisioner_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"), index=True)
    source_provisioner_id: Mapped[int | None] = mapped_column(ForeignKey("machine_provisioners.id", ondelete="SET NULL"))
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    region: Mapped[str | None] = mapped_column(String(128), index=True)
    environment: Mapped[str | None] = mapped_column(String(128), index=True)
    cpu: Mapped[float | None] = mapped_column(Float)
    ram_gb: Mapped[float | None] = mapped_column(Float)
    disk_gb: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[JsonDict] = mapped_column(JSONType, default=dict, nullable=False)

    platform: Mapped["Platform"] = relationship(back_populates="machines")
    application: Mapped["Application | None"] = relationship(back_populates="machines")
    source_provisioner: Mapped["MachineProvisioner | None"] = relationship(back_populates="machines")
    flavor_history: Mapped[list["MachineFlavorHistory"]] = relationship(
        back_populates="machine",
        cascade="all, delete-orphan",
    )


class MachineFlavorHistory(Base):
    """Audit row describing a machine flavor change over time."""
    __tablename__ = "machine_flavor_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    source_provisioner_id: Mapped[int | None] = mapped_column(ForeignKey("machine_provisioners.id", ondelete="SET NULL"))
    cpu: Mapped[float | None] = mapped_column(Float)
    ram_mb: Mapped[float | None] = mapped_column(Float)
    disk_mb: Mapped[float | None] = mapped_column(Float)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    machine: Mapped["Machine"] = relationship(back_populates="flavor_history")
    source_provisioner: Mapped["MachineProvisioner | None"] = relationship()


class MachineMetricMixin(TimestampMixin):
    """Shared columns for all daily machine metric tables."""
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("machine_providers.id", ondelete="CASCADE"), nullable=False)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date_value] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


class MachineCPUMetric(MachineMetricMixin, Base):
    """Daily CPU metric sample."""
    __tablename__ = "machine_cpu_metrics"
    __table_args__ = (
        UniqueConstraint("provider_id", "machine_id", "date", name="uq_machine_cpu_metrics_day"),
        Index("ix_machine_cpu_metrics_provider_date", "provider_id", "date"),
    )


class MachineRAMMetric(MachineMetricMixin, Base):
    """Daily RAM metric sample."""
    __tablename__ = "machine_ram_metrics"
    __table_args__ = (
        UniqueConstraint("provider_id", "machine_id", "date", name="uq_machine_ram_metrics_day"),
        Index("ix_machine_ram_metrics_provider_date", "provider_id", "date"),
    )


class MachineDiskMetric(MachineMetricMixin, Base):
    """Daily disk metric sample."""
    __tablename__ = "machine_disk_metrics"
    __table_args__ = (
        UniqueConstraint("provider_id", "machine_id", "date", name="uq_machine_disk_metrics_day"),
        Index("ix_machine_disk_metrics_provider_date", "provider_id", "date"),
    )


PROVISIONER_PROVIDER_TYPE_CONFLICT_DETAIL = "provisioner cannot have more than one provider of the same type"


def find_provider_type_conflict(
    provisioner: MachineProvisioner,
    provider_type: str,
    provider_id: int | None = None,
    candidate_provider: MachineProvider | None = None,
) -> MachineProvider | None:
    """Return the conflicting provider already attached to a provisioner, if any."""
    for provider in provisioner.providers:
        if candidate_provider is not None and provider is candidate_provider:
            continue
        if provider_id is not None and provider.id == provider_id:
            continue
        if provider.type == provider_type:
            return provider
    return None
