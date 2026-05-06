"""Runtime settings for the FastMCP gateway."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings for the MCP HTTP gateway."""

    app_name: str = "Metrics Collector"
    mcp_product_api_base_url: str = "http://127.0.0.1:8000"
    mcp_product_api_timeout_seconds: float = Field(default=30.0, gt=0)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the cached MCP settings instance."""

    return Settings()
