"""Application settings loaded from environment variables."""

import re
from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings for API, workers, and beat."""
    app_name: str = "Metrics Collector"
    app_env: Literal["dev", "test", "prod"] = "prod"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/washing_machine"
    database_schema: str = "app"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"
    celery_task_execution_retention_days: int = 90
    application_retention_days: int = 15
    machine_retention_days: int = 15
    scheduler_tick_seconds: int = 60
    application_inventory_sync_tick_seconds: int = 3600
    application_metrics_sync_tick_seconds: int = 3600
    application_metrics_sync_window_days: int = 5
    application_metrics_sync_batch_size: int = 0
    application_metrics_sync_retry_after_seconds: int = 3600
    flavor_optimization_window_size: int = 30
    flavor_optimization_min_cpu: int = 1
    flavor_optimization_max_cpu: int = 64
    flavor_optimization_min_ram_mb: int = 2048
    flavor_optimization_max_ram_mb: int = 262144
    prometheus_api_enabled: bool = True
    prometheus_api_path: str = "/metrics"
    celery_prometheus_enabled: bool = True
    celery_prometheus_port: int = 9101
    database_encryption_key: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_encryption_key")
    @classmethod
    def validate_database_encryption_key(cls, value: str) -> str:
        """Fail fast when the configured encryption key is missing or invalid."""
        Fernet(value.encode("utf-8"))
        return value

    @field_validator(
        "celery_task_execution_retention_days",
        "application_retention_days",
        "machine_retention_days",
    )
    @classmethod
    def validate_positive_retention_days(cls, value: int) -> int:
        """Require positive retention windows for maintenance cleanup tasks."""
        if value <= 0:
            raise ValueError("retention day settings must be greater than 0")
        return value

    @field_validator(
        "flavor_optimization_window_size",
        "flavor_optimization_min_cpu",
        "flavor_optimization_max_cpu",
        "flavor_optimization_min_ram_mb",
        "flavor_optimization_max_ram_mb",
    )
    @classmethod
    def validate_positive_optimization_settings(cls, value: int) -> int:
        """Require positive optimization windows and capacity bounds."""
        if value <= 0:
            raise ValueError("optimization settings must be greater than 0")
        return value

    @field_validator("flavor_optimization_min_ram_mb", "flavor_optimization_max_ram_mb")
    @classmethod
    def validate_ram_bounds_are_gib_aligned(cls, value: int) -> int:
        """Require RAM bounds to stay aligned on GiB-sized capacities."""
        if value % 1024 != 0:
            raise ValueError("RAM optimization bounds must be multiples of 1024")
        return value

    @field_validator("database_schema")
    @classmethod
    def validate_database_schema(cls, value: str) -> str:
        """Require a simple SQL identifier so schema selection stays safe."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("database_schema must be a simple SQL identifier")
        return value

    @model_validator(mode="after")
    def validate_optimization_bound_order(self) -> "Settings":
        """Keep optimization minimums below or equal to their maximums."""
        if self.flavor_optimization_min_cpu > self.flavor_optimization_max_cpu:
            raise ValueError("flavor_optimization_min_cpu must be less than or equal to flavor_optimization_max_cpu")
        if self.flavor_optimization_min_ram_mb > self.flavor_optimization_max_ram_mb:
            raise ValueError(
                "flavor_optimization_min_ram_mb must be less than or equal to flavor_optimization_max_ram_mb"
            )
        return self

    @property
    def is_dev(self) -> bool:
        """Return whether development-only features should be exposed."""
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()
