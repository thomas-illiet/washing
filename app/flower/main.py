"""Flower-specific Celery entrypoint.

This module intentionally avoids importing the application Celery bootstrap so
Flower can start without worker task registration, DB tracking, or app settings.
"""

from functools import lru_cache

from celery import Celery
from flower.urls import handlers as flower_handlers
from pydantic_settings import BaseSettings, SettingsConfigDict
from tornado.web import RequestHandler


class HealthHandler(RequestHandler):
    """Simple Flower health endpoint."""

    async def get(self) -> None:
        self.write("OK")


flower_handlers.insert(-1, (r"/health", HealthHandler))


class FlowerCelerySettings(BaseSettings):
    """Minimal Celery settings needed by Flower."""

    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_flower_celery_settings() -> FlowerCelerySettings:
    """Return the cached Flower Celery settings."""
    return FlowerCelerySettings()


settings = get_flower_celery_settings()

celery_app = Celery(
    "metrics_collector_flower",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

__all__ = ["HealthHandler", "celery_app", "get_flower_celery_settings"]
