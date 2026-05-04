from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
