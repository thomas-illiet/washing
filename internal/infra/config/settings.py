"""Application settings loaded from environment variables."""

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings for API, workers, and beat."""
    app_name: str = "Metrics Collector"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/metrics_collector"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"
    celery_beat_schedule_path: str = "/tmp/celerybeat-schedule"
    scheduler_tick_seconds: int = 60
    application_sync_tick_seconds: int = 3600
    application_sync_window_days: int = 5
    application_sync_batch_size: int = 0
    application_sync_retry_after_seconds: int = 3600
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


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()
