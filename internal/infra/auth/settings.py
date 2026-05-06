"""OIDC runtime settings shared by the API and MCP runtimes."""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class OIDCSettings(BaseSettings):
    """Typed settings for optional OIDC authentication and Swagger OAuth."""

    oidc_enabled: bool = False
    oidc_issuer_url: str | None = None
    oidc_discovery_url: str | None = None
    oidc_jwks_cache_ttl_seconds: int = 300
    oidc_role_claim_paths: Annotated[list[str], NoDecode] = [
        "realm_access.roles",
        "resource_access.*.roles",
        "roles",
    ]
    oidc_user_role_name: str = "user"
    oidc_admin_role_name: str = "admin"
    oidc_swagger_client_id: str | None = None
    oidc_swagger_use_pkce: bool = True
    oidc_swagger_scopes: Annotated[list[str], NoDecode] = ["openid", "profile", "email"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("oidc_role_claim_paths", "oidc_swagger_scopes", mode="before")
    @classmethod
    def split_csv_settings(cls, value):
        """Accept CSV or whitespace-delimited env values for list settings."""
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = value.replace("\n", ",").replace(" ", ",").split(",")
            return [item.strip() for item in raw_items if item.strip()]
        return value

    @field_validator("oidc_jwks_cache_ttl_seconds")
    @classmethod
    def validate_positive_ttl(cls, value: int) -> int:
        """Require a positive cache TTL when OIDC is enabled."""
        if value <= 0:
            raise ValueError("oidc_jwks_cache_ttl_seconds must be greater than 0")
        return value

    @model_validator(mode="after")
    def validate_required_oidc_fields(self) -> "OIDCSettings":
        """Require the minimum OIDC configuration when auth is enabled."""
        if not self.oidc_enabled:
            return self
        if not self.oidc_issuer_url:
            raise ValueError("oidc_issuer_url is required when oidc_enabled=true")
        if not self.oidc_role_claim_paths:
            raise ValueError("oidc_role_claim_paths must not be empty when oidc_enabled=true")
        if not self.oidc_user_role_name.strip():
            raise ValueError("oidc_user_role_name must not be empty when oidc_enabled=true")
        if not self.oidc_admin_role_name.strip():
            raise ValueError("oidc_admin_role_name must not be empty when oidc_enabled=true")
        if self.oidc_user_role_name == self.oidc_admin_role_name:
            raise ValueError("oidc_user_role_name and oidc_admin_role_name must be different")
        return self

    @property
    def discovery_url(self) -> str | None:
        """Return the explicit discovery URL or derive it from the issuer."""
        if self.oidc_discovery_url:
            return self.oidc_discovery_url
        if not self.oidc_issuer_url:
            return None
        return f"{self.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"


@lru_cache
def get_oidc_settings() -> OIDCSettings:
    """Return the cached OIDC settings instance."""

    return OIDCSettings()
