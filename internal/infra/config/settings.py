"""Application settings loaded from environment variables."""

import re
from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import field_validator
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
    prometheus_api_enabled: bool = True
    prometheus_api_path: str = "/metrics"
    celery_prometheus_enabled: bool = True
    celery_prometheus_port: int = 9101
    integration_config_encryption_key: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("integration_config_encryption_key")
    @classmethod
    def validate_integration_config_encryption_key(cls, value: str) -> str:
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

    @field_validator("database_schema")
    @classmethod
    def validate_database_schema(cls, value: str) -> str:
        """Require a simple SQL identifier so schema selection stays safe."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("database_schema must be a simple SQL identifier")
        return value

    @property
    def is_dev(self) -> bool:
        """Return whether development-only features should be exposed."""
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()
